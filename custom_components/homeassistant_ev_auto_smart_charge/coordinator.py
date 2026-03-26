"""Data coordinator: spot prices + SOC -> cheapest-hour plan."""

from __future__ import annotations

import logging
import math

_LOGGER = logging.getLogger(__name__)
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import CALLBACK_TYPE, HassJob, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CHARGE_ORDER_MODE_ECONOMICAL,
    CHARGE_ORDER_MODE_MANUAL,
    CHARGE_PRIORITY_BALANCED,
    CHARGE_PRIORITY_EV1_FIRST,
    CHARGE_PRIORITY_EV2_FIRST,
    CONF_CHARGER_POWER_KW,
    CONF_CHARGE_ORDER_MODE,
    CONF_CHARGE_PRIORITY,
    CONF_EV1_CAPACITY_KWH,
    CONF_EV1_DONE_BY,
    CONF_EV1_DEVICE_ID,
    CONF_EV1_HOME_ENTITY,
    CONF_EV1_SOC_SENSOR,
    CONF_EV2_CAPACITY_KWH,
    CONF_EV2_DONE_BY,
    CONF_EV2_DEVICE_ID,
    CONF_EV2_HOME_ENTITY,
    CONF_EV2_SOC_SENSOR,
    CONF_PRICE_DEVICE_ID,
    CONF_PRICE_SENSOR,
    CONF_TARGET_SOC_PERCENT,
    CONF_ZAPTEC_CHARGER_DEVICE_ID,
    DEFAULT_CHARGE_PRIORITY,
    DEFAULT_CHARGE_ORDER_MODE,
    DEFAULT_CHARGER_KW,
    DEFAULT_TARGET_SOC,
    DOMAIN,
    UPDATE_INTERVAL_MIN,
    ZAPTEC_CALC_PHASES,
    ZAPTEC_CALC_VOLTAGE_V,
)
from .device_resolve import (
    resolve_spot_price_sensor,
    resolve_zaptec_charger_max_current_entity,
    ResolvedEVDevice,
    entity_ids_for_device,
    is_plugged_in,
    resolve_ev_from_device,
)


def _parse_hour(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        parsed = dt_util.parse_datetime(value)
        if parsed:
            return parsed
    return None


_SOC_ATTR_KEYS = (
    "battery_level",
    "state_of_charge",
    "soc",
    "battery_soc",
)


def _parse_float_maybe_percent(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", ".")
    if s.endswith("%"):
        s = s[:-1].strip()
    if not s or s in ("unknown", "unavailable"):
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _normalize_soc_to_percent(raw: float, unit: str | None) -> float:
    u = (unit or "").strip().lower()
    if u == "%":
        return max(0.0, min(100.0, raw))
    if 0.0 < raw <= 1.0:
        return max(0.0, min(100.0, raw * 100.0))
    return max(0.0, min(100.0, raw))


def _soc_percent_from_ev_state(state: State | None) -> float | None:
    """Battery % from entity state or common EV integration attributes."""

    if state is None or state.state in ("unknown", "unavailable"):
        return None

    unit = state.attributes.get("unit_of_measurement")
    unit_str = str(unit).strip() if unit is not None else None

    val = None
    if state.state not in (None, ""):
        val = _parse_float_maybe_percent(state.state)

    if val is None:
        for key in _SOC_ATTR_KEYS:
            if key not in state.attributes:
                continue
            val = _parse_float_maybe_percent(state.attributes.get(key))
            if val is not None:
                break

    if val is None:
        return None

    return _normalize_soc_to_percent(val, unit_str)


def _target_percent_from_resolved(
    hass: HomeAssistant,
    resolved: ResolvedEVDevice,
    fallback_percent: float,
) -> float:
    """Charge limit / target SOC from device number/sensor, else options fallback."""

    if not resolved.target_entity_id:
        return fallback_percent
    st = hass.states.get(resolved.target_entity_id)
    if st is None or st.state in ("unknown", "unavailable", None, ""):
        return fallback_percent
    pct = _soc_percent_from_ev_state(st)
    if pct is None:
        raw = _parse_float_maybe_percent(st.state)
        if raw is not None:
            uom = st.attributes.get("unit_of_measurement")
            pct = _normalize_soc_to_percent(
                raw, str(uom).strip() if uom is not None else None
            )
    return fallback_percent if pct is None else pct


def _presence_plug_for_plan(
    hass: HomeAssistant,
    opt: dict[str, Any],
    resolved: ResolvedEVDevice,
    legacy_home_key: str,
) -> tuple[bool | None, bool, bool | None]:
    """(at_home display, unused legacy second value, plugged display).

    Plug/home are for UI/binary sensors only. Cheapest-hour and immediate costs
    always use full kWh needed to reach target SOC (not gated on cable/home).
    """

    plugged = is_plugged_in(hass, resolved.connected_entity_id)

    if resolved.home_entity_id:
        st = hass.states.get(resolved.home_entity_id)
        if st is None or st.state in ("unknown", "unavailable", None, ""):
            if plugged is False:
                return (None, False, False)
            return (None, True, plugged)
        h = _state_indicates_home(st)
        if plugged is False:
            return (h, False, False)
        if plugged is True:
            return (h, True, plugged)
        if h is False:
            return (False, False, plugged)
        return (h, True, plugged)

    home_disp, inc = _presence_display_and_plan(hass, opt, legacy_home_key)
    if plugged is False:
        return (home_disp, False, False)
    if plugged is True:
        return (home_disp, True, plugged)
    if home_disp is False:
        return (False, False, plugged)
    return (home_disp, inc, plugged)


def _merge_price_slots_from_attributes(
    attrs: dict[str, Any],
) -> list[tuple[datetime, float]]:
    raw_today = attrs.get("raw_today") or []
    raw_tomorrow = attrs.get("raw_tomorrow") or []
    slots: list[tuple[datetime, float]] = []

    for block in (raw_today, raw_tomorrow):
        if not isinstance(block, list):
            continue
        for row in block:
            if not isinstance(row, dict):
                continue
            h = _parse_hour(row.get("hour"))
            if h is None:
                continue
            price_val = None
            for key in ("price", "value", "total"):
                if key not in row or row[key] is None:
                    continue
                price_val = _parse_float_maybe_percent(row[key])
                if price_val is not None:
                    break
            if price_val is None:
                continue
            slots.append((dt_util.as_local(h), float(price_val)))

    slots.sort(key=lambda x: x[0])
    return slots


def _merge_price_slots(
    hass: HomeAssistant, price_entity: str
) -> list[tuple[datetime, float]]:
    state = hass.states.get(price_entity)
    if state is None:
        return []
    return _merge_price_slots_from_attributes(dict(state.attributes))


def _normalize_charge_priority(raw: Any) -> str:
    v = str(raw or "").strip().lower().replace("-", "_")
    if v in (CHARGE_PRIORITY_EV1_FIRST, "ev1"):
        return CHARGE_PRIORITY_EV1_FIRST
    if v in (CHARGE_PRIORITY_EV2_FIRST, "ev2"):
        return CHARGE_PRIORITY_EV2_FIRST
    return CHARGE_PRIORITY_BALANCED


def _normalize_charge_order_mode(raw: Any) -> str:
    v = str(raw or "").strip().lower().replace("-", "_")
    if v == CHARGE_ORDER_MODE_ECONOMICAL:
        return CHARGE_ORDER_MODE_ECONOMICAL
    return CHARGE_ORDER_MODE_MANUAL


def _default_done_by_today(hour: int) -> datetime:
    now = dt_util.now()
    return now.replace(hour=hour, minute=0, second=0, microsecond=0)


def _default_done_by_tomorrow(hour: int) -> datetime:
    base = _default_done_by_today(hour)
    return dt_util.as_local(base + timedelta(days=1))


def _parse_done_by(raw: Any, default_dt: datetime) -> datetime:
    parsed = _parse_hour(raw)
    if parsed is None:
        return default_dt
    if parsed.tzinfo is None:
        return dt_util.as_local(parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE))
    return dt_util.as_local(parsed)


def _state_indicates_home(state: State) -> bool | None:
    domain = state.domain
    s = (state.state or "").lower()
    if domain in ("device_tracker", "person"):
        if s == "home":
            return True
        if s in ("not_home", "away"):
            return False
        return None
    if domain in ("binary_sensor", "input_boolean"):
        if s == STATE_ON.lower():
            return True
        if s == STATE_OFF.lower():
            return False
        return None
    if s in ("home", "on", "yes", "true"):
        return True
    if s in ("not_home", "away", "off", "no", "false"):
        return False
    return None


def _presence_display_and_plan(
    hass: HomeAssistant, opt: dict[str, Any], key: str
) -> tuple[bool | None, bool]:
    """(UI at-home or None if unknown / not configured, include kWh in plan)."""

    raw_id = opt.get(key)
    entity_id = (str(raw_id).strip() if raw_id else "") or ""
    if not entity_id:
        return (None, True)

    st = hass.states.get(entity_id)
    if st is None or st.state in ("unknown", "unavailable", None, ""):
        return (None, True)

    home = _state_indicates_home(st)
    if home is None:
        return (None, True)
    return (home, home)


def _deliver_one_hour_kwh(
    rem1: float,
    rem2: float,
    cap_kw: float,
    priority: str,
) -> tuple[float, float, float, float]:
    """kWh to EV1, EV2 this hour, then remaining rem1, rem2."""

    rem1 = max(0.0, rem1)
    rem2 = max(0.0, rem2)
    cap_kw = max(0.0, cap_kw)
    if rem1 <= 1e-12 and rem2 <= 1e-12:
        return (0.0, 0.0, rem1, rem2)

    if priority == CHARGE_PRIORITY_EV1_FIRST:
        d1 = min(rem1, cap_kw)
        d2 = min(rem2, cap_kw - d1)
        return (d1, d2, rem1 - d1, rem2 - d2)

    if priority == CHARGE_PRIORITY_EV2_FIRST:
        d2 = min(rem2, cap_kw)
        d1 = min(rem1, cap_kw - d2)
        return (d1, d2, rem1 - d1, rem2 - d2)

    total = rem1 + rem2
    deliver = min(cap_kw, total)
    if total <= 1e-12:
        return (0.0, 0.0, rem1, rem2)
    d1 = min(rem1, deliver * rem1 / total)
    d2 = min(rem2, deliver - d1)
    slack = deliver - d1 - d2
    if slack > 1e-9:
        add1 = min(slack, rem1 - d1)
        d1 += add1
        slack -= add1
        d2 += min(slack, rem2 - d2)
    return (d1, d2, rem1 - d1, rem2 - d2)


def _sequential_energy_costs(
    hours_ordered: list[tuple[datetime, float]],
    charger_kw: float,
    start_rem1: float,
    start_rem2: float,
    priority: str,
) -> tuple[float, float, float]:
    rem1, rem2 = max(0.0, start_rem1), max(0.0, start_rem2)
    c1 = c2 = 0.0
    for _h, price in hours_ordered:
        if rem1 <= 1e-9 and rem2 <= 1e-9:
            break
        d1, d2, rem1, rem2 = _deliver_one_hour_kwh(
            rem1, rem2, charger_kw, priority
        )
        c1 += price * d1
        c2 += price * d2
    return (c1, c2, c1 + c2)


def _hour_eligible(hour_start: datetime, done_by: datetime) -> bool:
    return (hour_start + timedelta(hours=1)) <= done_by


def _choose_effective_priority(
    mode: str,
    future_hours: list[tuple[datetime, float]],
    charger_kw: float,
    kwh1: float,
    kwh2: float,
    done_by1: datetime,
    done_by2: datetime,
    manual_priority: str,
) -> str:
    if mode != CHARGE_ORDER_MODE_ECONOMICAL:
        return manual_priority

    ev1_first_cost, _, _, _ = _build_feasible_schedule(
        future_hours, charger_kw, kwh1, kwh2, done_by1, done_by2, CHARGE_PRIORITY_EV1_FIRST
    )
    ev2_first_cost, _, _, _ = _build_feasible_schedule(
        future_hours, charger_kw, kwh1, kwh2, done_by1, done_by2, CHARGE_PRIORITY_EV2_FIRST
    )
    if ev1_first_cost is None and ev2_first_cost is None:
        return manual_priority
    if ev1_first_cost is None:
        return CHARGE_PRIORITY_EV2_FIRST
    if ev2_first_cost is None:
        return CHARGE_PRIORITY_EV1_FIRST
    return CHARGE_PRIORITY_EV1_FIRST if ev1_first_cost <= ev2_first_cost else CHARGE_PRIORITY_EV2_FIRST


def _build_feasible_schedule(
    future_hours: list[tuple[datetime, float]],
    charger_kw: float,
    kwh1: float,
    kwh2: float,
    done_by1: datetime,
    done_by2: datetime,
    priority: str,
) -> tuple[float | None, list[dict[str, Any]], float, float]:
    """Return (total_cost, selected_slots, rem1, rem2) honoring per-EV deadlines."""
    rem1 = max(0.0, kwh1)
    rem2 = max(0.0, kwh2)
    if rem1 <= 1e-12 and rem2 <= 1e-12:
        return (0.0, [], 0.0, 0.0)

    hours_by_price = sorted(future_hours, key=lambda x: x[1])
    total_cost = 0.0
    selected: list[dict[str, Any]] = []

    for hour_start, price in hours_by_price:
        if rem1 <= 1e-9 and rem2 <= 1e-9:
            break
        eligible1 = _hour_eligible(hour_start, done_by1)
        eligible2 = _hour_eligible(hour_start, done_by2)
        if not eligible1 and not eligible2:
            continue

        future_after = [h for h, _p in future_hours if h > hour_start]
        cap1_future = (
            sum(1 for h in future_after if _hour_eligible(h, done_by1)) * charger_kw
        )
        cap2_future = (
            sum(1 for h in future_after if _hour_eligible(h, done_by2)) * charger_kw
        )
        must1 = max(0.0, rem1 - cap1_future) if eligible1 else 0.0
        must2 = max(0.0, rem2 - cap2_future) if eligible2 else 0.0
        if must1 + must2 > charger_kw + 1e-9:
            return (None, [], rem1, rem2)

        d1 = min(must1, rem1)
        d2 = min(must2, rem2)
        cap_left = charger_kw - d1 - d2
        if cap_left > 1e-12:
            if priority == CHARGE_PRIORITY_EV1_FIRST:
                if eligible1:
                    add = min(cap_left, rem1 - d1)
                    d1 += add
                    cap_left -= add
                if cap_left > 1e-12 and eligible2:
                    d2 += min(cap_left, rem2 - d2)
            elif priority == CHARGE_PRIORITY_EV2_FIRST:
                if eligible2:
                    add = min(cap_left, rem2 - d2)
                    d2 += add
                    cap_left -= add
                if cap_left > 1e-12 and eligible1:
                    d1 += min(cap_left, rem1 - d1)
            else:
                left1 = (rem1 - d1) if eligible1 else 0.0
                left2 = (rem2 - d2) if eligible2 else 0.0
                total_left = left1 + left2
                if total_left > 1e-12:
                    add1 = min(left1, cap_left * left1 / total_left)
                    add2 = min(left2, cap_left - add1)
                    d1 += add1
                    d2 += add2

        rem1 -= d1
        rem2 -= d2
        delivered = d1 + d2
        if delivered > 1e-12:
            total_cost += delivered * price
            selected.append(
                {
                    "hour": hour_start.isoformat(),
                    "price": price,
                    "energy_kwh": round(delivered, 4),
                    "ev1_kwh": round(d1, 4),
                    "ev2_kwh": round(d2, 4),
                }
            )

    if rem1 > 1e-6 or rem2 > 1e-6:
        return (None, [], rem1, rem2)

    selected.sort(key=lambda x: x["hour"])
    return (total_cost, selected, rem1, rem2)


def _solo_cheapest_cost_for_need(
    future: list[tuple[datetime, float]],
    charger_kw: float,
    kwh_need: float,
) -> float | None:
    """Cheapest-hour cost if only this EV charged (its full kWh need), ignoring the other car."""

    if kwh_need <= 1e-12:
        return 0.0
    if not future:
        return None
    hours = int(math.ceil(kwh_need / charger_kw))
    pick = sorted(future, key=lambda x: x[1])[:hours]
    pick.sort(key=lambda x: x[1])
    rem = kwh_need
    total = 0.0
    for _h, p in pick:
        if rem <= 1e-12:
            break
        take = min(charger_kw, rem)
        total += p * take
        rem -= take
    return total


@dataclass
class PlanResult:
    """Computed charge plan."""

    ev1_soc: float | None
    ev2_soc: float | None
    ev1_kwh_needed: float
    ev2_kwh_needed: float
    total_kwh_needed: float
    hours_to_charge: int
    charger_power_kw: float
    selected_slots: list[dict[str, Any]]
    estimated_cost: float | None
    estimated_ev1_cost: float | None
    estimated_ev2_cost: float | None
    charging_window_start: str | None
    charging_window_end: str | None
    charging_schedule_summary: str | None
    currency: str | None
    price_unit: str | None
    tomorrow_valid: bool | None
    error: str | None
    ev1_target_percent: float | None = None
    ev2_target_percent: float | None = None
    ev1_at_home: bool | None = None
    ev2_at_home: bool | None = None
    charge_priority: str = DEFAULT_CHARGE_PRIORITY
    ev1_planned_kwh: float = 0.0
    ev2_planned_kwh: float = 0.0
    immediate_ev1_cost: float | None = None
    immediate_ev2_cost: float | None = None
    immediate_total_cost: float | None = None
    ev1_connected: bool | None = None
    ev2_connected: bool | None = None
    ev1_solo_cheapest_cost: float | None = None
    ev2_solo_cheapest_cost: float | None = None


class EvAutoSmartChargeCoordinator(DataUpdateCoordinator[PlanResult]):
    """Merge Energi Data Service prices with two EV SOC sensors."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.config_entry = entry
        super().__init__(
            hass,
            logger=logging.getLogger(__name__),
            name=DOMAIN,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MIN),
        )

    @property
    def price_sensor(self) -> str:
        opt = self._options()
        dev = opt.get(CONF_PRICE_DEVICE_ID)
        if dev:
            eid = resolve_spot_price_sensor(self.hass, dev)
            if eid:
                return eid
        legacy = opt.get(CONF_PRICE_SENSOR)
        return str(legacy).strip() if legacy else ""

    def _resolved_ev(self, slot: int) -> ResolvedEVDevice:
        opt = self._options()
        if slot == 1:
            did = opt.get(CONF_EV1_DEVICE_ID)
            if did:
                return resolve_ev_from_device(self.hass, did, plug_platform="tesla")
            soc = (str(opt.get(CONF_EV1_SOC_SENSOR) or "")).strip()
            return ResolvedEVDevice(device_id="", soc_entity_id=soc or None)
        did = opt.get(CONF_EV2_DEVICE_ID)
        if did:
            return resolve_ev_from_device(self.hass, did, plug_platform="vw")
        soc = (str(opt.get(CONF_EV2_SOC_SENSOR) or "")).strip()
        return ResolvedEVDevice(device_id="", soc_entity_id=soc or None)

    def _options(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    def _effective_charger_kw(self, opt: dict[str, Any]) -> float:
        """Manual kW, or Zaptec **Charger max current** × 3 × 230 V / 1000 when configured."""

        manual = float(opt.get(CONF_CHARGER_POWER_KW, DEFAULT_CHARGER_KW))
        zdev = opt.get(CONF_ZAPTEC_CHARGER_DEVICE_ID)
        if not zdev or not str(zdev).strip():
            return manual
        eid = resolve_zaptec_charger_max_current_entity(
            self.hass, str(zdev).strip()
        )
        if not eid:
            return manual
        st = self.hass.states.get(eid)
        if st is None or st.state in ("unknown", "unavailable", None, ""):
            return manual
        try:
            amps = float(st.state)
        except (TypeError, ValueError):
            return manual
        if amps <= 0:
            return manual
        return (
            amps * float(ZAPTEC_CALC_PHASES) * ZAPTEC_CALC_VOLTAGE_V / 1000.0
        )

    async def _async_update_data(self) -> PlanResult:
        return self._compute_plan()

    def _compute_plan(self) -> PlanResult:
        opt = self._options()
        priority = _normalize_charge_priority(opt.get(CONF_CHARGE_PRIORITY))
        order_mode = _normalize_charge_order_mode(
            opt.get(CONF_CHARGE_ORDER_MODE, DEFAULT_CHARGE_ORDER_MODE)
        )
        cap1 = float(opt[CONF_EV1_CAPACITY_KWH])
        cap2 = float(opt[CONF_EV2_CAPACITY_KWH])
        charger_kw = self._effective_charger_kw(opt)
        done_by1 = _parse_done_by(
            opt.get(CONF_EV1_DONE_BY), _default_done_by_today(22)
        )
        done_by2 = _parse_done_by(
            opt.get(CONF_EV2_DONE_BY), _default_done_by_tomorrow(8)
        )

        if charger_kw <= 0:
            return PlanResult(
                ev1_soc=None,
                ev2_soc=None,
                ev1_kwh_needed=0.0,
                ev2_kwh_needed=0.0,
                total_kwh_needed=0.0,
                hours_to_charge=0,
                charger_power_kw=charger_kw,
                selected_slots=[],
                estimated_cost=None,
                estimated_ev1_cost=None,
                estimated_ev2_cost=None,
                charging_window_start=None,
                charging_window_end=None,
                charging_schedule_summary=None,
                currency=None,
                price_unit=None,
                tomorrow_valid=None,
                error="charger_power_kw must be positive",
                charge_priority=priority,
            )

        r1 = self._resolved_ev(1)
        r2 = self._resolved_ev(2)
        fb_target = float(opt.get(CONF_TARGET_SOC_PERCENT, DEFAULT_TARGET_SOC))

        if not r1.soc_entity_id or not r2.soc_entity_id:
            return PlanResult(
                ev1_soc=None,
                ev2_soc=None,
                charge_priority=priority,
                ev1_kwh_needed=0.0,
                ev2_kwh_needed=0.0,
                total_kwh_needed=0.0,
                hours_to_charge=0,
                charger_power_kw=charger_kw,
                selected_slots=[],
                estimated_cost=None,
                estimated_ev1_cost=None,
                estimated_ev2_cost=None,
                charging_window_start=None,
                charging_window_end=None,
                charging_schedule_summary=None,
                currency=None,
                price_unit=None,
                tomorrow_valid=None,
                error="Both EV devices must be selected (Settings → reconfigure if upgrading).",
            )

        target1 = _target_percent_from_resolved(self.hass, r1, fb_target)
        target2 = _target_percent_from_resolved(self.hass, r2, fb_target)

        s1 = self.hass.states.get(r1.soc_entity_id)
        s2 = self.hass.states.get(r2.soc_entity_id)
        ps = self.hass.states.get(self.price_sensor)

        soc1 = _soc_percent_from_ev_state(s1)
        soc2 = _soc_percent_from_ev_state(s2)

        kwh1 = (
            max(0.0, cap1 * max(0.0, target1 - soc1) / 100.0)
            if soc1 is not None
            else 0.0
        )
        kwh2 = (
            max(0.0, cap2 * max(0.0, target2 - soc2) / 100.0)
            if soc2 is not None
            else 0.0
        )

        ev1_home_disp, _inc1, plug1 = _presence_plug_for_plan(
            self.hass, opt, r1, CONF_EV1_HOME_ENTITY
        )
        ev2_home_disp, _inc2, plug2 = _presence_plug_for_plan(
            self.hass, opt, r2, CONF_EV2_HOME_ENTITY
        )

        if soc1 is None or soc2 is None:
            return PlanResult(
                ev1_soc=soc1,
                ev2_soc=soc2,
                ev1_kwh_needed=kwh1,
                ev2_kwh_needed=kwh2,
                total_kwh_needed=kwh1 + kwh2,
                hours_to_charge=0,
                charger_power_kw=charger_kw,
                selected_slots=[],
                estimated_cost=None,
                estimated_ev1_cost=None,
                estimated_ev2_cost=None,
                charging_window_start=None,
                charging_window_end=None,
                charging_schedule_summary=None,
                currency=None,
                price_unit=None,
                tomorrow_valid=None,
                error="EV SOC sensor unavailable",
                ev1_target_percent=target1,
                ev2_target_percent=target2,
                ev1_at_home=ev1_home_disp,
                ev2_at_home=ev2_home_disp,
                charge_priority=priority,
                ev1_connected=plug1,
                ev2_connected=plug2,
            )

        total_kwh = kwh1 + kwh2

        if total_kwh <= 0:
            return PlanResult(
                ev1_soc=soc1,
                ev2_soc=soc2,
                ev1_kwh_needed=kwh1,
                ev2_kwh_needed=kwh2,
                total_kwh_needed=0.0,
                hours_to_charge=0,
                charger_power_kw=charger_kw,
                selected_slots=[],
                estimated_cost=0.0,
                estimated_ev1_cost=0.0,
                estimated_ev2_cost=0.0,
                charging_window_start=None,
                charging_window_end=None,
                charging_schedule_summary=None,
                currency=ps.attributes.get("currency") if ps else None,
                price_unit=ps.attributes.get("unit") if ps else None,
                tomorrow_valid=ps.attributes.get("tomorrow_valid") if ps else None,
                error=None,
                ev1_target_percent=target1,
                ev2_target_percent=target2,
                ev1_at_home=ev1_home_disp,
                ev2_at_home=ev2_home_disp,
                charge_priority=priority,
                ev1_planned_kwh=0.0,
                ev2_planned_kwh=0.0,
                immediate_ev1_cost=0.0,
                immediate_ev2_cost=0.0,
                immediate_total_cost=0.0,
                ev1_connected=plug1,
                ev2_connected=plug2,
            )

        slots = _merge_price_slots(self.hass, self.price_sensor)
        now = dt_util.now()
        window_start = now.replace(minute=0, second=0, microsecond=0)
        latest_done_by = max(done_by1, done_by2)
        future = (
            [
                (h, p)
                for h, p in slots
                if h >= window_start and (h + timedelta(hours=1)) <= latest_done_by
            ]
            if slots
            else []
        )
        effective_priority = _choose_effective_priority(
            order_mode,
            future,
            charger_kw,
            kwh1,
            kwh2,
            done_by1,
            done_by2,
            priority,
        )
        solo1 = _solo_cheapest_cost_for_need(future, charger_kw, kwh1)
        solo2 = _solo_cheapest_cost_for_need(future, charger_kw, kwh2)

        if not slots:
            return PlanResult(
                ev1_soc=soc1,
                ev2_soc=soc2,
                ev1_kwh_needed=kwh1,
                ev2_kwh_needed=kwh2,
                total_kwh_needed=total_kwh,
                hours_to_charge=0,
                charger_power_kw=charger_kw,
                selected_slots=[],
                estimated_cost=None,
                estimated_ev1_cost=None,
                estimated_ev2_cost=None,
                charging_window_start=None,
                charging_window_end=None,
                charging_schedule_summary=None,
                currency=ps.attributes.get("currency") if ps else None,
                price_unit=ps.attributes.get("unit") if ps else None,
                tomorrow_valid=ps.attributes.get("tomorrow_valid") if ps else None,
                error="No hourly prices (check Energi Data Service sensor and raw_today/raw_tomorrow)",
                ev1_target_percent=target1,
                ev2_target_percent=target2,
                ev1_at_home=ev1_home_disp,
                ev2_at_home=ev2_home_disp,
                charge_priority=effective_priority,
                ev1_planned_kwh=kwh1,
                ev2_planned_kwh=kwh2,
                immediate_ev1_cost=None,
                immediate_ev2_cost=None,
                immediate_total_cost=None,
                ev1_connected=plug1,
                ev2_connected=plug2,
                ev1_solo_cheapest_cost=solo1,
                ev2_solo_cheapest_cost=solo2,
            )

        if not future:
            return PlanResult(
                ev1_soc=soc1,
                ev2_soc=soc2,
                ev1_kwh_needed=kwh1,
                ev2_kwh_needed=kwh2,
                total_kwh_needed=total_kwh,
                hours_to_charge=0,
                charger_power_kw=charger_kw,
                selected_slots=[],
                estimated_cost=None,
                estimated_ev1_cost=None,
                estimated_ev2_cost=None,
                charging_window_start=None,
                charging_window_end=None,
                charging_schedule_summary=None,
                currency=ps.attributes.get("currency") if ps else None,
                price_unit=ps.attributes.get("unit") if ps else None,
                tomorrow_valid=ps.attributes.get("tomorrow_valid") if ps else None,
                error="No future price hours before configured done-by deadlines",
                ev1_target_percent=target1,
                ev2_target_percent=target2,
                ev1_at_home=ev1_home_disp,
                ev2_at_home=ev2_home_disp,
                charge_priority=effective_priority,
                ev1_planned_kwh=kwh1,
                ev2_planned_kwh=kwh2,
                immediate_ev1_cost=None,
                immediate_ev2_cost=None,
                immediate_total_cost=None,
                ev1_connected=plug1,
                ev2_connected=plug2,
                ev1_solo_cheapest_cost=solo1,
                ev2_solo_cheapest_cost=solo2,
            )

        future_chrono = sorted(future, key=lambda x: x[0])
        im1, im2, imtot = _sequential_energy_costs(
            future_chrono, charger_kw, kwh1, kwh2, effective_priority
        )
        est_cost, selected, rem1, rem2 = _build_feasible_schedule(
            future, charger_kw, kwh1, kwh2, done_by1, done_by2, effective_priority
        )
        if est_cost is None or not selected:
            return PlanResult(
                ev1_soc=soc1,
                ev2_soc=soc2,
                ev1_kwh_needed=kwh1,
                ev2_kwh_needed=kwh2,
                total_kwh_needed=total_kwh,
                hours_to_charge=0,
                charger_power_kw=charger_kw,
                selected_slots=[],
                estimated_cost=None,
                estimated_ev1_cost=None,
                estimated_ev2_cost=None,
                charging_window_start=None,
                charging_window_end=None,
                charging_schedule_summary=None,
                currency=ps.attributes.get("currency") if ps else None,
                price_unit=ps.attributes.get("unit") if ps else None,
                tomorrow_valid=ps.attributes.get("tomorrow_valid") if ps else None,
                error=(
                    "Unable to satisfy one or both done-by deadlines with available "
                    "price hours and charger power"
                ),
                ev1_target_percent=target1,
                ev2_target_percent=target2,
                ev1_at_home=ev1_home_disp,
                ev2_at_home=ev2_home_disp,
                charge_priority=effective_priority,
                ev1_planned_kwh=max(0.0, kwh1 - rem1),
                ev2_planned_kwh=max(0.0, kwh2 - rem2),
                immediate_ev1_cost=im1,
                immediate_ev2_cost=im2,
                immediate_total_cost=imtot,
                ev1_connected=plug1,
                ev2_connected=plug2,
                ev1_solo_cheapest_cost=solo1,
                ev2_solo_cheapest_cost=solo2,
            )

        first_h = dt_util.parse_datetime(selected[0]["hour"])
        last_h = dt_util.parse_datetime(selected[-1]["hour"])
        hours_needed = len(selected)
        if first_h is None or last_h is None:
            window_start_iso = None
            window_end_iso = None
            schedule_summary = None
        else:
            start_local = dt_util.as_local(first_h)
            end_local = dt_util.as_local(last_h) + timedelta(hours=1)
            window_start_iso = start_local.isoformat()
            window_end_iso = end_local.isoformat()
            schedule_summary = (
                f"{start_local.strftime('%a %Y-%m-%d %H:%M')}–{end_local.strftime('%H:%M')} "
                f"local ({hours_needed} h)"
            )

        ev1_cost = sum(float(s["price"]) * float(s["ev1_kwh"]) for s in selected)
        ev2_cost = sum(float(s["price"]) * float(s["ev2_kwh"]) for s in selected)

        return PlanResult(
            ev1_soc=soc1,
            ev2_soc=soc2,
            ev1_kwh_needed=kwh1,
            ev2_kwh_needed=kwh2,
            total_kwh_needed=total_kwh,
            hours_to_charge=hours_needed,
            charger_power_kw=charger_kw,
            selected_slots=selected,
            estimated_cost=est_cost,
            estimated_ev1_cost=ev1_cost,
            estimated_ev2_cost=ev2_cost,
            charging_window_start=window_start_iso,
            charging_window_end=window_end_iso,
            charging_schedule_summary=schedule_summary,
            currency=ps.attributes.get("currency") if ps else None,
            price_unit=ps.attributes.get("unit") if ps else None,
            tomorrow_valid=ps.attributes.get("tomorrow_valid") if ps else None,
            error=None,
            ev1_target_percent=target1,
            ev2_target_percent=target2,
            ev1_at_home=ev1_home_disp,
            ev2_at_home=ev2_home_disp,
            charge_priority=effective_priority,
            ev1_planned_kwh=max(0.0, kwh1 - rem1),
            ev2_planned_kwh=max(0.0, kwh2 - rem2),
            immediate_ev1_cost=im1,
            immediate_ev2_cost=im2,
            immediate_total_cost=imtot,
            ev1_connected=plug1,
            ev2_connected=plug2,
            ev1_solo_cheapest_cost=solo1,
            ev2_solo_cheapest_cost=solo2,
        )

    @callback
    def _async_state_changed(self, _event: Any) -> None:
        self.hass.async_run_hass_job(HassJob(self.async_request_refresh))


def _tracked_entity_ids_for_coordinator(
    hass: HomeAssistant, coordinator: EvAutoSmartChargeCoordinator
) -> list[str]:
    """Entity IDs whose state/attribute changes should recompute the plan."""

    entities: list[str] = []
    opt = {**coordinator.config_entry.data, **coordinator.config_entry.options}
    price_dev = opt.get(CONF_PRICE_DEVICE_ID)
    if price_dev:
        entities.extend(entity_ids_for_device(hass, price_dev))
    else:
        ps = opt.get(CONF_PRICE_SENSOR)
        if ps and str(ps).strip():
            entities.append(str(ps).strip())
    ps_resolved = coordinator.price_sensor
    if ps_resolved and str(ps_resolved).strip():
        entities.append(str(ps_resolved).strip())

    for dev_key, plug_pf in (
        (CONF_EV1_DEVICE_ID, "tesla"),
        (CONF_EV2_DEVICE_ID, "vw"),
    ):
        did = opt.get(dev_key)
        if not did:
            continue
        entities.extend(entity_ids_for_device(hass, did))
        resolved = resolve_ev_from_device(hass, did, plug_platform=plug_pf)
        for eid in (
            resolved.soc_entity_id,
            resolved.target_entity_id,
            resolved.connected_entity_id,
            resolved.home_entity_id,
        ):
            if eid and str(eid).strip():
                entities.append(str(eid).strip())

    for key in (CONF_EV1_HOME_ENTITY, CONF_EV2_HOME_ENTITY):
        eid = opt.get(key)
        if eid and str(eid).strip():
            entities.append(str(eid).strip())
    for soc_key in (CONF_EV1_SOC_SENSOR, CONF_EV2_SOC_SENSOR):
        eid = opt.get(soc_key)
        if eid and str(eid).strip():
            entities.append(str(eid).strip())

    zc_dev = opt.get(CONF_ZAPTEC_CHARGER_DEVICE_ID)
    if zc_dev and str(zc_dev).strip():
        zid = str(zc_dev).strip()
        entities.extend(entity_ids_for_device(hass, zid))
        z_amp = resolve_zaptec_charger_max_current_entity(hass, zid)
        if z_amp:
            entities.append(z_amp)

    out = [e for e in entities if e and str(e).strip()]
    return list(dict.fromkeys(out))


def setup_coordinator_state_listener(
    hass: HomeAssistant, coordinator: EvAutoSmartChargeCoordinator
) -> CALLBACK_TYPE:
    """Subscribe when HA is running; refresh on price/EV state and attribute updates."""

    unsub_track: CALLBACK_TYPE | None = None

    @callback
    def _on_state(_event: Any) -> None:
        coordinator._async_state_changed(_event)

    @callback
    def _register_tracker(_hass: HomeAssistant) -> None:
        nonlocal unsub_track
        entities = _tracked_entity_ids_for_coordinator(_hass, coordinator)
        if not entities:
            _LOGGER.warning(
                "No source entities to watch — plan updates only every %s minutes",
                UPDATE_INTERVAL_MIN,
            )
            return
        unsub_track = async_track_state_change_event(_hass, entities, _on_state)

    unsub_at_started = async_at_started(hass, _register_tracker)

    def _teardown() -> None:
        nonlocal unsub_track
        if unsub_track is not None:
            unsub_track()
            unsub_track = None
        unsub_at_started()

    return _teardown

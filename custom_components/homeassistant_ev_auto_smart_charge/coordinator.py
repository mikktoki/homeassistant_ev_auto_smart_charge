"""Data coordinator: spot prices + SOC -> cheapest-hour plan."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CHARGER_POWER_KW,
    CONF_EV1_CAPACITY_KWH,
    CONF_EV1_SOC_SENSOR,
    CONF_EV1_TARGET_SOC_SENSOR,
    CONF_EV2_CAPACITY_KWH,
    CONF_EV2_SOC_SENSOR,
    CONF_EV2_TARGET_SOC_SENSOR,
    CONF_PRICE_SENSOR,
    CONF_TARGET_SOC_PERCENT,
    DEFAULT_CHARGER_KW,
    DEFAULT_TARGET_SOC,
    DOMAIN,
    UPDATE_INTERVAL_MIN,
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


def _target_soc_percent_from_config(
    hass: HomeAssistant, opt: dict[str, Any], sensor_key: str
) -> tuple[float | None, str | None]:
    """Resolve target SOC %: optional entity, else CONF_TARGET_SOC_PERCENT."""

    raw_id = opt.get(sensor_key)
    entity_id = (str(raw_id).strip() if raw_id else "") or ""
    if not entity_id:
        return (
            float(opt.get(CONF_TARGET_SOC_PERCENT, DEFAULT_TARGET_SOC)),
            None,
        )

    st = hass.states.get(entity_id)
    pct = _soc_percent_from_ev_state(st)
    if pct is None:
        return (None, "Target SOC entity unavailable")
    return (pct, None)


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
            price = row.get("price")
            if h is None or price is None:
                continue
            try:
                slots.append((dt_util.as_local(h), float(price)))
            except (TypeError, ValueError):
                continue

    slots.sort(key=lambda x: x[0])
    return slots


def _merge_price_slots(
    hass: HomeAssistant, price_entity: str
) -> list[tuple[datetime, float]]:
    state = hass.states.get(price_entity)
    if state is None:
        return []
    return _merge_price_slots_from_attributes(dict(state.attributes))


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
        return self.config_entry.data[CONF_PRICE_SENSOR]

    @property
    def ev1_soc_sensor(self) -> str:
        return self.config_entry.data[CONF_EV1_SOC_SENSOR]

    @property
    def ev2_soc_sensor(self) -> str:
        return self.config_entry.data[CONF_EV2_SOC_SENSOR]

    def _options(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    async def _async_update_data(self) -> PlanResult:
        return self._compute_plan()

    def _compute_plan(self) -> PlanResult:
        opt = self._options()
        cap1 = float(opt[CONF_EV1_CAPACITY_KWH])
        cap2 = float(opt[CONF_EV2_CAPACITY_KWH])
        charger_kw = float(opt.get(CONF_CHARGER_POWER_KW, DEFAULT_CHARGER_KW))

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
            )

        target1, terr1 = _target_soc_percent_from_config(
            self.hass, opt, CONF_EV1_TARGET_SOC_SENSOR
        )
        target2, terr2 = _target_soc_percent_from_config(
            self.hass, opt, CONF_EV2_TARGET_SOC_SENSOR
        )
        if terr1 or terr2:
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
                error=terr1 or terr2,
                ev1_target_percent=target1,
                ev2_target_percent=target2,
            )

        s1 = self.hass.states.get(self.ev1_soc_sensor)
        s2 = self.hass.states.get(self.ev2_soc_sensor)
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
            )

        slots = _merge_price_slots(self.hass, self.price_sensor)
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
            )

        now = dt_util.now()
        window_start = now.replace(minute=0, second=0, microsecond=0)
        future = [(h, p) for h, p in slots if h >= window_start]
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
                error="No future price hours in raw data",
                ev1_target_percent=target1,
                ev2_target_percent=target2,
            )

        hours_needed = int(math.ceil(total_kwh / charger_kw))
        sorted_by_price = sorted(future, key=lambda x: x[1])
        chosen = sorted_by_price[:hours_needed]
        chosen.sort(key=lambda x: x[0])

        est_cost = sum(p * charger_kw for _, p in chosen)
        ev1_cost = est_cost * (kwh1 / total_kwh)
        ev2_cost = est_cost * (kwh2 / total_kwh)

        first_h, _ = chosen[0]
        last_h, _ = chosen[-1]
        start_local = dt_util.as_local(first_h)
        end_local = dt_util.as_local(last_h) + timedelta(hours=1)
        window_start_iso = start_local.isoformat()
        window_end_iso = end_local.isoformat()
        schedule_summary = (
            f"{start_local.strftime('%a %Y-%m-%d %H:%M')}–{end_local.strftime('%H:%M')} "
            f"local ({hours_needed} h)"
        )

        selected = [
            {
                "hour": h.isoformat(),
                "price": p,
                "energy_kwh": charger_kw,
            }
            for h, p in chosen
        ]

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
        )

    @callback
    def _async_state_changed(self, _event: Any) -> None:
        self.hass.async_create_task(self.async_request_refresh())


def setup_coordinator_state_listener(
    hass: HomeAssistant, coordinator: EvAutoSmartChargeCoordinator
) -> CALLBACK_TYPE:
    """Subscribe to price + SOC entities; caller should register with entry.async_on_unload."""

    entities = [
        coordinator.price_sensor,
        coordinator.ev1_soc_sensor,
        coordinator.ev2_soc_sensor,
    ]
    opt = {**coordinator.config_entry.data, **coordinator.config_entry.options}
    for key in (CONF_EV1_TARGET_SOC_SENSOR, CONF_EV2_TARGET_SOC_SENSOR):
        eid = opt.get(key)
        if eid and str(eid).strip():
            entities.append(str(eid).strip())

    entities = list(dict.fromkeys(entities))

    @callback
    def _on_state(event: Any) -> None:
        coordinator._async_state_changed(event)

    return async_track_state_change_event(hass, entities, _on_state)

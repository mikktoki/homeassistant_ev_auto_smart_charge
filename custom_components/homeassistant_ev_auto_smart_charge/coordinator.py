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
    CONF_EV2_CAPACITY_KWH,
    CONF_EV2_SOC_SENSOR,
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


def _float_state(state: State | None) -> float | None:
    if state is None or state.state in ("unknown", "unavailable", None, ""):
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None


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
    currency: str | None
    price_unit: str | None
    tomorrow_valid: bool | None
    error: str | None


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
        target = float(opt.get(CONF_TARGET_SOC_PERCENT, DEFAULT_TARGET_SOC))

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
                currency=None,
                price_unit=None,
                tomorrow_valid=None,
                error="charger_power_kw must be positive",
            )

        s1 = self.hass.states.get(self.ev1_soc_sensor)
        s2 = self.hass.states.get(self.ev2_soc_sensor)
        ps = self.hass.states.get(self.price_sensor)

        soc1 = _float_state(s1)
        soc2 = _float_state(s2)

        kwh1 = (
            max(0.0, cap1 * max(0.0, target - soc1) / 100.0) if soc1 is not None else 0.0
        )
        kwh2 = (
            max(0.0, cap2 * max(0.0, target - soc2) / 100.0) if soc2 is not None else 0.0
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
                currency=None,
                price_unit=None,
                tomorrow_valid=None,
                error="EV SOC sensor unavailable",
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
                currency=ps.attributes.get("currency") if ps else None,
                price_unit=ps.attributes.get("unit") if ps else None,
                tomorrow_valid=ps.attributes.get("tomorrow_valid") if ps else None,
                error=None,
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
                currency=ps.attributes.get("currency") if ps else None,
                price_unit=ps.attributes.get("unit") if ps else None,
                tomorrow_valid=ps.attributes.get("tomorrow_valid") if ps else None,
                error="No hourly prices (check Energi Data Service sensor and raw_today/raw_tomorrow)",
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
                currency=ps.attributes.get("currency") if ps else None,
                price_unit=ps.attributes.get("unit") if ps else None,
                tomorrow_valid=ps.attributes.get("tomorrow_valid") if ps else None,
                error="No future price hours in raw data",
            )

        hours_needed = int(math.ceil(total_kwh / charger_kw))
        sorted_by_price = sorted(future, key=lambda x: x[1])
        chosen = sorted_by_price[:hours_needed]
        chosen.sort(key=lambda x: x[0])

        est_cost = sum(p * charger_kw for _, p in chosen)
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
            currency=ps.attributes.get("currency") if ps else None,
            price_unit=ps.attributes.get("unit") if ps else None,
            tomorrow_valid=ps.attributes.get("tomorrow_valid") if ps else None,
            error=None,
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

    @callback
    def _on_state(event: Any) -> None:
        coordinator._async_state_changed(event)

    return async_track_state_change_event(hass, entities, _on_state)

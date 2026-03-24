"""Sensor exposing the cheapest-hour charge plan."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, INTEGRATION_VERSION
from .coordinator import EvAutoSmartChargeCoordinator, PlanResult


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EvAutoSmartChargeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ChargePlanSensor(coordinator, entry)])


class ChargePlanSensor(CoordinatorEntity[EvAutoSmartChargeCoordinator], SensorEntity):
    """Estimated cost to charge both EVs in the cheapest upcoming hours."""

    _attr_has_entity_name = True
    entity_description = SensorEntityDescription(
        key="charge_plan",
        translation_key="charge_plan",
    )

    def __init__(
        self, coordinator: EvAutoSmartChargeCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_charge_plan"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "homeassistant-ev_auto_smart_charge",
            "model": "EV Auto Smart Charge",
            "sw_version": INTEGRATION_VERSION,
        }

    @property
    def native_value(self) -> float | str | None:
        data = self.coordinator.data
        if not isinstance(data, PlanResult):
            return None
        if data.error:
            return None
        if data.total_kwh_needed <= 0:
            return 0.0
        return data.estimated_cost

    @property
    def native_unit_of_measurement(self) -> str | None:
        data = self.coordinator.data
        if isinstance(data, PlanResult) and data.currency:
            return str(data.currency)
        return None

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if not isinstance(data, PlanResult):
            return {}

        attrs = {
            "ev1_soc_percent": data.ev1_soc,
            "ev2_soc_percent": data.ev2_soc,
            "ev1_target_soc_percent": data.ev1_target_percent,
            "ev2_target_soc_percent": data.ev2_target_percent,
            "ev1_at_home": data.ev1_at_home,
            "ev2_at_home": data.ev2_at_home,
            "ev1_plugged_in": data.ev1_connected,
            "ev2_plugged_in": data.ev2_connected,
            "charge_priority": data.charge_priority,
            "ev1_planned_kwh": round(data.ev1_planned_kwh, 3),
            "ev2_planned_kwh": round(data.ev2_planned_kwh, 3),
            "ev1_kwh_needed": round(data.ev1_kwh_needed, 3),
            "ev2_kwh_needed": round(data.ev2_kwh_needed, 3),
            "total_kwh_needed": round(data.total_kwh_needed, 3),
            "hours_to_charge": data.hours_to_charge,
            "charger_power_kw": data.charger_power_kw,
            "cheapest_hours": data.selected_slots,
            "charging_window_start": data.charging_window_start,
            "charging_window_end": data.charging_window_end,
            "charging_schedule_summary": data.charging_schedule_summary,
            "price_unit": data.price_unit,
            "tomorrow_prices_valid": data.tomorrow_valid,
        }
        if data.error:
            attrs["error"] = data.error
        planned_sum = data.ev1_planned_kwh + data.ev2_planned_kwh
        attrs["planned_total_kwh"] = round(planned_sum, 3)
        if data.estimated_cost is not None:
            attrs["estimated_total_cost"] = round(data.estimated_cost, 4)
        if data.estimated_cost is not None and planned_sum > 0:
            attrs["effective_price_per_kwh"] = round(
                data.estimated_cost / planned_sum, 6
            )
        if data.estimated_ev1_cost is not None:
            attrs["estimated_ev1_cost"] = round(data.estimated_ev1_cost, 4)
        if data.estimated_ev2_cost is not None:
            attrs["estimated_ev2_cost"] = round(data.estimated_ev2_cost, 4)
        if data.ev1_solo_cheapest_cost is not None:
            attrs["ev1_cheapest_if_alone_cost"] = round(
                data.ev1_solo_cheapest_cost, 4
            )
        if data.ev2_solo_cheapest_cost is not None:
            attrs["ev2_cheapest_if_alone_cost"] = round(
                data.ev2_solo_cheapest_cost, 4
            )
        if data.immediate_ev1_cost is not None:
            attrs["immediate_charge_ev1_cost"] = round(data.immediate_ev1_cost, 4)
        if data.immediate_ev2_cost is not None:
            attrs["immediate_charge_ev2_cost"] = round(data.immediate_ev2_cost, 4)
        if data.immediate_total_cost is not None:
            attrs["immediate_charge_total_cost"] = round(
                data.immediate_total_cost, 4
            )
        return attrs

    @property
    def available(self) -> bool:
        return isinstance(self.coordinator.data, PlanResult)

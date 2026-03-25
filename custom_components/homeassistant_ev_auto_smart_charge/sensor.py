"""Sensors for the cheapest-hour charge plan (one entity per value)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, INTEGRATION_VERSION
from .coordinator import EvAutoSmartChargeCoordinator, PlanResult


def _device_info(entry: ConfigEntry) -> dict:
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": entry.title,
        "manufacturer": "homeassistant-ev_auto_smart_charge",
        "model": "EV Auto Smart Charge",
        "sw_version": INTEGRATION_VERSION,
    }


class ChargePlanSensor(
    CoordinatorEntity[EvAutoSmartChargeCoordinator], SensorEntity
):
    """Primary entity: estimated cost to charge in the planned cheap hours."""

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
        self._attr_device_info = _device_info(entry)

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
    def available(self) -> bool:
        return isinstance(self.coordinator.data, PlanResult)


class EvAutoPlanSensor(CoordinatorEntity[EvAutoSmartChargeCoordinator], SensorEntity):
    """Single plan field as its own sensor."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        coordinator: EvAutoSmartChargeCoordinator,
        entry: ConfigEntry,
        description: SensorEntityDescription,
        value_fn: Callable[[PlanResult], Any],
        native_uom_fn: Callable[[PlanResult], str | None] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._value_fn = value_fn
        self._native_uom_fn = native_uom_fn
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data
        if not isinstance(data, PlanResult):
            return None
        return self._value_fn(data)

    @property
    def native_unit_of_measurement(self) -> str | None:
        data = self.coordinator.data
        if not isinstance(data, PlanResult):
            return self.entity_description.native_unit_of_measurement
        if self._native_uom_fn is not None:
            u = self._native_uom_fn(data)
            if u is not None:
                return u
        return self.entity_description.native_unit_of_measurement

    @property
    def native_currency(self) -> str | None:
        if self.entity_description.device_class != SensorDeviceClass.MONETARY:
            return None
        data = self.coordinator.data
        if isinstance(data, PlanResult) and data.currency:
            return str(data.currency)
        return None

    @property
    def available(self) -> bool:
        return isinstance(self.coordinator.data, PlanResult)


def _build_auxiliary_sensors(
    coordinator: EvAutoSmartChargeCoordinator, entry: ConfigEntry
) -> list[SensorEntity]:
    """All former attributes as dedicated sensors."""

    def _currency_uom(d: PlanResult) -> str | None:
        return str(d.currency) if d.currency else None

    specs: list[
        tuple[
            SensorEntityDescription,
            Callable[[PlanResult], Any],
            Callable[[PlanResult], str | None] | None,
        ]
    ] = [
        (
            SensorEntityDescription(
                key="ev1_soc",
                translation_key="ev1_soc",
                native_unit_of_measurement="%",
                device_class=SensorDeviceClass.BATTERY,
                suggested_display_precision=1,
            ),
            lambda d: d.ev1_soc,
            None,
        ),
        (
            SensorEntityDescription(
                key="ev2_soc",
                translation_key="ev2_soc",
                native_unit_of_measurement="%",
                device_class=SensorDeviceClass.BATTERY,
                suggested_display_precision=1,
            ),
            lambda d: d.ev2_soc,
            None,
        ),
        (
            SensorEntityDescription(
                key="ev1_target_soc",
                translation_key="ev1_target_soc",
                native_unit_of_measurement="%",
                suggested_display_precision=1,
            ),
            lambda d: d.ev1_target_percent,
            None,
        ),
        (
            SensorEntityDescription(
                key="ev2_target_soc",
                translation_key="ev2_target_soc",
                native_unit_of_measurement="%",
                suggested_display_precision=1,
            ),
            lambda d: d.ev2_target_percent,
            None,
        ),
        (
            SensorEntityDescription(
                key="charge_priority",
                translation_key="charge_priority",
            ),
            lambda d: d.charge_priority,
            None,
        ),
        (
            SensorEntityDescription(
                key="ev1_planned_kwh",
                translation_key="ev1_planned_kwh",
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                device_class=SensorDeviceClass.ENERGY,
                suggested_display_precision=3,
            ),
            lambda d: round(d.ev1_planned_kwh, 3),
            None,
        ),
        (
            SensorEntityDescription(
                key="ev2_planned_kwh",
                translation_key="ev2_planned_kwh",
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                device_class=SensorDeviceClass.ENERGY,
                suggested_display_precision=3,
            ),
            lambda d: round(d.ev2_planned_kwh, 3),
            None,
        ),
        (
            SensorEntityDescription(
                key="ev1_kwh_needed",
                translation_key="ev1_kwh_needed",
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                device_class=SensorDeviceClass.ENERGY,
                suggested_display_precision=3,
            ),
            lambda d: round(d.ev1_kwh_needed, 3),
            None,
        ),
        (
            SensorEntityDescription(
                key="ev2_kwh_needed",
                translation_key="ev2_kwh_needed",
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                device_class=SensorDeviceClass.ENERGY,
                suggested_display_precision=3,
            ),
            lambda d: round(d.ev2_kwh_needed, 3),
            None,
        ),
        (
            SensorEntityDescription(
                key="total_kwh_needed",
                translation_key="total_kwh_needed",
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                device_class=SensorDeviceClass.ENERGY,
                suggested_display_precision=3,
            ),
            lambda d: round(d.total_kwh_needed, 3),
            None,
        ),
        (
            SensorEntityDescription(
                key="planned_total_kwh",
                translation_key="planned_total_kwh",
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                device_class=SensorDeviceClass.ENERGY,
                suggested_display_precision=3,
            ),
            lambda d: round(d.ev1_planned_kwh + d.ev2_planned_kwh, 3),
            None,
        ),
        (
            SensorEntityDescription(
                key="hours_to_charge",
                translation_key="hours_to_charge",
                native_unit_of_measurement="h",
            ),
            lambda d: d.hours_to_charge,
            None,
        ),
        (
            SensorEntityDescription(
                key="charger_power_kw",
                translation_key="charger_power_kw",
                native_unit_of_measurement=UnitOfPower.KILO_WATT,
                device_class=SensorDeviceClass.POWER,
                suggested_display_precision=2,
            ),
            lambda d: d.charger_power_kw,
            None,
        ),
        (
            SensorEntityDescription(
                key="effective_price_per_kwh",
                translation_key="effective_price_per_kwh",
                suggested_display_precision=6,
            ),
            lambda d: (
                round(
                    d.estimated_cost / (d.ev1_planned_kwh + d.ev2_planned_kwh),
                    6,
                )
                if d.estimated_cost is not None
                and (d.ev1_planned_kwh + d.ev2_planned_kwh) > 0
                else None
            ),
            lambda d: (
                f"{d.currency}/kWh" if d.currency and d.price_unit else d.price_unit
            ),
        ),
        (
            SensorEntityDescription(
                key="estimated_ev1_cost",
                translation_key="estimated_ev1_cost",
                device_class=SensorDeviceClass.MONETARY,
                suggested_display_precision=4,
            ),
            lambda d: (
                round(d.estimated_ev1_cost, 4)
                if d.estimated_ev1_cost is not None
                else None
            ),
            _currency_uom,
        ),
        (
            SensorEntityDescription(
                key="estimated_ev2_cost",
                translation_key="estimated_ev2_cost",
                device_class=SensorDeviceClass.MONETARY,
                suggested_display_precision=4,
            ),
            lambda d: (
                round(d.estimated_ev2_cost, 4)
                if d.estimated_ev2_cost is not None
                else None
            ),
            _currency_uom,
        ),
        (
            SensorEntityDescription(
                key="ev1_cheapest_if_alone_cost",
                translation_key="ev1_cheapest_if_alone_cost",
                device_class=SensorDeviceClass.MONETARY,
                suggested_display_precision=4,
            ),
            lambda d: (
                round(d.ev1_solo_cheapest_cost, 4)
                if d.ev1_solo_cheapest_cost is not None
                else None
            ),
            _currency_uom,
        ),
        (
            SensorEntityDescription(
                key="ev2_cheapest_if_alone_cost",
                translation_key="ev2_cheapest_if_alone_cost",
                device_class=SensorDeviceClass.MONETARY,
                suggested_display_precision=4,
            ),
            lambda d: (
                round(d.ev2_solo_cheapest_cost, 4)
                if d.ev2_solo_cheapest_cost is not None
                else None
            ),
            _currency_uom,
        ),
        (
            SensorEntityDescription(
                key="immediate_charge_ev1_cost",
                translation_key="immediate_charge_ev1_cost",
                device_class=SensorDeviceClass.MONETARY,
                suggested_display_precision=4,
            ),
            lambda d: (
                round(d.immediate_ev1_cost, 4)
                if d.immediate_ev1_cost is not None
                else None
            ),
            _currency_uom,
        ),
        (
            SensorEntityDescription(
                key="immediate_charge_ev2_cost",
                translation_key="immediate_charge_ev2_cost",
                device_class=SensorDeviceClass.MONETARY,
                suggested_display_precision=4,
            ),
            lambda d: (
                round(d.immediate_ev2_cost, 4)
                if d.immediate_ev2_cost is not None
                else None
            ),
            _currency_uom,
        ),
        (
            SensorEntityDescription(
                key="immediate_charge_total_cost",
                translation_key="immediate_charge_total_cost",
                device_class=SensorDeviceClass.MONETARY,
                suggested_display_precision=4,
            ),
            lambda d: (
                round(d.immediate_total_cost, 4)
                if d.immediate_total_cost is not None
                else None
            ),
            _currency_uom,
        ),
        (
            SensorEntityDescription(
                key="charging_window_start",
                translation_key="charging_window_start",
                device_class=SensorDeviceClass.TIMESTAMP,
            ),
            lambda d: (
                dt_util.parse_datetime(d.charging_window_start)
                if d.charging_window_start
                else None
            ),
            None,
        ),
        (
            SensorEntityDescription(
                key="charging_window_end",
                translation_key="charging_window_end",
                device_class=SensorDeviceClass.TIMESTAMP,
            ),
            lambda d: (
                dt_util.parse_datetime(d.charging_window_end)
                if d.charging_window_end
                else None
            ),
            None,
        ),
        (
            SensorEntityDescription(
                key="charging_schedule_summary",
                translation_key="charging_schedule_summary",
            ),
            lambda d: d.charging_schedule_summary,
            None,
        ),
        (
            SensorEntityDescription(
                key="price_unit",
                translation_key="price_unit",
            ),
            lambda d: d.price_unit,
            None,
        ),
        (
            SensorEntityDescription(
                key="cheapest_hours",
                translation_key="cheapest_hours",
            ),
            lambda d: json.dumps(d.selected_slots) if d.selected_slots else "[]",
            None,
        ),
        (
            SensorEntityDescription(
                key="plan_error",
                translation_key="plan_error",
            ),
            lambda d: d.error,
            None,
        ),
    ]

    out: list[SensorEntity] = []
    for desc, vfn, uom_fn in specs:
        uom_callable = uom_fn if uom_fn is not None else None
        out.append(EvAutoPlanSensor(coordinator, entry, desc, vfn, uom_callable))
    return out


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EvAutoSmartChargeCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [ChargePlanSensor(coordinator, entry)]
    entities.extend(_build_auxiliary_sensors(coordinator, entry))
    async_add_entities(entities)

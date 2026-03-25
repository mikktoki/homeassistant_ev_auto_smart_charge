"""Binary sensors for EV plan presence, plug state, and price validity."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

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


class EvAutoPlanBinarySensor(
    CoordinatorEntity[EvAutoSmartChargeCoordinator], BinarySensorEntity
):
    """Plan field exposed as a binary sensor."""

    def __init__(
        self,
        coordinator: EvAutoSmartChargeCoordinator,
        entry: ConfigEntry,
        description: BinarySensorEntityDescription,
        value_fn: Callable[[PlanResult], bool | None],
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._value_fn = value_fn
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if not isinstance(data, PlanResult):
            return None
        return self._value_fn(data)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EvAutoSmartChargeCoordinator = hass.data[DOMAIN][entry.entry_id]

    specs: list[
        tuple[BinarySensorEntityDescription, Callable[[PlanResult], bool | None]]
    ] = [
        (
            BinarySensorEntityDescription(
                key="ev1_at_home",
                translation_key="ev1_at_home",
            ),
            lambda d: d.ev1_at_home,
        ),
        (
            BinarySensorEntityDescription(
                key="ev2_at_home",
                translation_key="ev2_at_home",
            ),
            lambda d: d.ev2_at_home,
        ),
        (
            BinarySensorEntityDescription(
                key="ev1_plugged_in",
                translation_key="ev1_plugged_in",
                device_class=BinarySensorDeviceClass.PLUG,
            ),
            lambda d: d.ev1_connected,
        ),
        (
            BinarySensorEntityDescription(
                key="ev2_plugged_in",
                translation_key="ev2_plugged_in",
                device_class=BinarySensorDeviceClass.PLUG,
            ),
            lambda d: d.ev2_connected,
        ),
        (
            BinarySensorEntityDescription(
                key="tomorrow_prices_valid",
                translation_key="tomorrow_prices_valid",
            ),
            lambda d: d.tomorrow_valid,
        ),
    ]

    async_add_entities(
        EvAutoPlanBinarySensor(coordinator, entry, desc, fn)
        for desc, fn in specs
    )

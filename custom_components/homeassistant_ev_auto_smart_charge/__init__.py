"""EV Auto Smart Charge — spot prices + two EV SOC → cheapest-hour plan."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_EV1_DEVICE_ID,
    CONF_EV1_SOC_SENSOR,
    CONF_EV2_DEVICE_ID,
    CONF_EV2_SOC_SENSOR,
    CONF_PRICE_DEVICE_ID,
    CONF_PRICE_SENSOR,
    DOMAIN,
)
from .coordinator import EvAutoSmartChargeCoordinator, setup_coordinator_state_listener

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """v1→v2: SOC entities → EV devices. v2→v3: price sensor → Energi Data Service device."""

    if entry.version >= 3:
        return True

    data = {**entry.data}
    registry = er.async_get(hass)

    if entry.version < 2:
        for soc_key, dev_key in (
            (CONF_EV1_SOC_SENSOR, CONF_EV1_DEVICE_ID),
            (CONF_EV2_SOC_SENSOR, CONF_EV2_DEVICE_ID),
        ):
            ent_id = data.get(soc_key)
            if not ent_id or data.get(dev_key):
                continue
            reg = registry.async_get(ent_id)
            if reg and reg.device_id:
                data[dev_key] = reg.device_id
                data.pop(soc_key, None)

    if entry.version < 3:
        price_ent = data.get(CONF_PRICE_SENSOR)
        if price_ent and not data.get(CONF_PRICE_DEVICE_ID):
            preg = registry.async_get(price_ent)
            if preg and preg.device_id:
                data[CONF_PRICE_DEVICE_ID] = preg.device_id
                data.pop(CONF_PRICE_SENSOR, None)

    hass.config_entries.async_update_entry(entry, data=data, version=3)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = EvAutoSmartChargeCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    entry.async_on_unload(setup_coordinator_state_listener(hass, coordinator))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

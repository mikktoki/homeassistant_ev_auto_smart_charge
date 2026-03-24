"""Map a Home Assistant device to Tesla / VW-style EV entities."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _entries_for_device(
    registry: er.EntityRegistry, device_id: str
) -> list[RegistryEntry]:
    """HA compatibility: older cores have no include_disabled on async_entries_for_device."""

    entries = er.async_entries_for_device(registry, device_id)
    return [e for e in entries if not e.disabled_by]


@dataclass
class ResolvedEVDevice:
    """Entities discovered on one vehicle device."""

    device_id: str
    soc_entity_id: str | None = None
    target_entity_id: str | None = None
    connected_entity_id: str | None = None
    home_entity_id: str | None = None


def _device_class(hass: HomeAssistant, entity_id: str) -> str | None:
    st = hass.states.get(entity_id)
    if st is None:
        return None
    dc = st.attributes.get("device_class")
    return str(dc) if dc is not None else None


def _best_entry(
    hass: HomeAssistant,
    entries: list[RegistryEntry],
    score_fn,
) -> RegistryEntry | None:
    best: RegistryEntry | None = None
    best_s = -1
    for entry in entries:
        if entry.disabled_by:
            continue
        s = score_fn(hass, entry)
        if s > best_s:
            best_s = s
            best = entry
    return best if best_s > 0 else None


def _score_soc(hass: HomeAssistant, entry: RegistryEntry) -> int:
    if entry.domain != "sensor":
        return 0
    eid = entry.entity_id.lower()
    dc = _device_class(hass, entry.entity_id)
    if dc == "battery":
        return 100
    if "battery_level" in eid:
        return 95
    if "battery" in eid and "level" in eid:
        return 90
    if "state_of_charge" in eid or eid.endswith("_soc"):
        return 85
    if "soc" in eid:
        return 80
    return 0


def _score_target(hass: HomeAssistant, entry: RegistryEntry) -> int:
    eid = entry.entity_id.lower()
    if entry.domain == "number":
        if "charge_limit" in eid or "charging_limit" in eid:
            return 100
        if "charge" in eid and "limit" in eid:
            return 95
        if "target" in eid and "soc" in eid:
            return 90
        if "max_range" in eid or "maxrange" in eid:
            return 75
        if "charge" in eid:
            return 70
    if entry.domain == "sensor" and "charge" in eid and "limit" in eid:
        return 80
    return 0


def _score_connected(hass: HomeAssistant, entry: RegistryEntry) -> int:
    eid = entry.entity_id.lower()
    skip = (
        "charging_state",
        "charger_lock",
        "charger_power",
        "polling",
        "climate",
        "sentry",
        "software",
        "update",
        "window",
        "door_lock",
        "frunk",
        "trunk",
    )
    if any(x in eid for x in skip):
        return 0
    if entry.domain == "binary_sensor":
        if "connector" in eid or "cable" in eid or "plug" in eid:
            return 100
        if "charger" in eid and "wall" not in eid:
            return 85
        if "vehicle_connected" in eid:
            return 95
        return 0
    if entry.domain == "sensor":
        if "plug" in eid or "cable" in eid or "connector" in eid:
            return 90
        if "charging" in eid and "cable" in eid:
            return 88
    return 0


def _score_home(_hass: HomeAssistant, entry: RegistryEntry) -> int:
    if entry.domain == "device_tracker":
        return 100
    return 0


def resolve_ev_from_device(hass: HomeAssistant, device_id: str) -> ResolvedEVDevice:
    """Pick SOC, charge limit, plug/cable, and location entities for a device."""

    registry = er.async_get(hass)
    entries = _entries_for_device(registry, device_id)
    if not entries:
        _LOGGER.warning("No entities on device %s", device_id)
        return ResolvedEVDevice(device_id=device_id)

    soc_e = _best_entry(hass, entries, _score_soc)
    target_e = _best_entry(hass, entries, _score_target)
    conn_e = _best_entry(hass, entries, _score_connected)
    home_e = _best_entry(hass, entries, _score_home)

    return ResolvedEVDevice(
        device_id=device_id,
        soc_entity_id=soc_e.entity_id if soc_e else None,
        target_entity_id=target_e.entity_id if target_e else None,
        connected_entity_id=conn_e.entity_id if conn_e else None,
        home_entity_id=home_e.entity_id if home_e else None,
    )


def entity_ids_for_device(hass: HomeAssistant, device_id: str) -> list[str]:
    """All entity ids on a device (for state subscriptions)."""

    registry = er.async_get(hass)
    entries = _entries_for_device(registry, device_id)
    return [e.entity_id for e in entries]


def is_plugged_in(hass: HomeAssistant, entity_id: str | None) -> bool | None:
    """Interpret cable/connector/plug entity; None if unknown."""

    if not entity_id:
        return None
    st = hass.states.get(entity_id)
    if st is None or st.state in ("unknown", "unavailable", None, ""):
        return None
    domain = st.domain
    s = (st.state or "").lower()
    if domain == "binary_sensor":
        if s == STATE_ON.lower():
            return True
        if s == STATE_OFF.lower():
            return False
        return None
    if domain == "sensor":
        if s in ("connected", "plugged", "plug_connected", "on", "yes", "true"):
            return True
        if s in (
            "disconnected",
            "plug_not_connected",
            "not_connected",
            "off",
            "no",
            "false",
        ):
            return False
    return None

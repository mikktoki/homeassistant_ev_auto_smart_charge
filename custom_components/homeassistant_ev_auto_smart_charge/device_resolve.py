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


def _friendly_lower(hass: HomeAssistant, entity_id: str) -> str:
    st = hass.states.get(entity_id)
    if not st:
        return ""
    fn = st.attributes.get("friendly_name")
    return str(fn).lower().strip() if fn else ""


def _score_connected_tesla(hass: HomeAssistant, entry: RegistryEntry, eid: str) -> int:
    """Prefer Tesla / Tesla Custom *Charger* plug entity, not generic connectivity."""

    skip = (
        "charging_state",
        "charger_lock",
        "charger_power",
        "charger_voltage",
        "charger_energy",
        "charger_phases",
        "charger_current",
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
    fn = _friendly_lower(hass, entry.entity_id)
    tk = (entry.translation_key or "").lower()

    if entry.domain == "binary_sensor":
        if fn == "charger":
            return 150
        if tk == "charger":
            return 145
        oid = eid.split(".", 1)[-1]
        if eid.endswith("_charger") or oid == "charger":
            return 140
        if "wall_connector" in eid or "wallcharger" in eid:
            return 0
        if "connector" in eid or "cable" in eid or "plug" in eid:
            return 100
        if "charger" in eid:
            return 95
        if "vehicle_connected" in eid:
            return 35
    if entry.domain == "sensor":
        if fn == "charger" or tk == "charger":
            return 130
        if "plug" in eid or "cable" in eid or "connector" in eid:
            return 75
    return 0


def _score_connected_vw(hass: HomeAssistant, entry: RegistryEntry, eid: str) -> int:
    """Prefer VW-family *Charging cable connected* style entities."""

    skip = (
        "charging_state",
        "charger_power",
        "charger_voltage",
        "charger_phases",
        "polling",
        "climate",
        "software",
        "update",
        "window",
        "door_lock",
    )
    if any(x in eid for x in skip):
        return 0
    fn = _friendly_lower(hass, entry.entity_id)
    tk = (entry.translation_key or "").lower()
    blob = f"{eid} {tk} {fn}"

    if "charging cable connected" in fn or "charging_cable_connected" in blob.replace(
        " ", "_"
    ):
        return 150
    if tk in ("charging_cable_connected", "plug_connection"):
        return 145
    if "charging_cable_connected" in eid:
        return 140
    if "charging" in eid and "cable" in eid and "connected" in eid:
        return 135
    if entry.domain in ("sensor", "binary_sensor"):
        if "cable" in eid and "connected" in eid:
            return 125
        if "charging_cable" in eid:
            return 115
        if "connector" in eid or "plug" in eid:
            return 95
    return 0


def _score_connected_generic(hass: HomeAssistant, entry: RegistryEntry, eid: str) -> int:
    skip = (
        "charging_state",
        "charger_lock",
        "charger_power",
        "charger_voltage",
        "charger_energy",
        "charger_phases",
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


def _score_connected(
    hass: HomeAssistant, entry: RegistryEntry, plug_platform: str | None
) -> int:
    eid = entry.entity_id.lower()
    if plug_platform == "tesla":
        s = _score_connected_tesla(hass, entry, eid)
        if s > 0:
            return s
        g = _score_connected_generic(hass, entry, eid)
        if "vehicle_connected" in eid:
            return 0
        return g
    if plug_platform == "vw":
        s = _score_connected_vw(hass, entry, eid)
        return s if s > 0 else _score_connected_generic(hass, entry, eid)
    return _score_connected_generic(hass, entry, eid)


def _score_home(_hass: HomeAssistant, entry: RegistryEntry) -> int:
    if entry.domain == "device_tracker":
        return 100
    return 0


def resolve_ev_from_device(
    hass: HomeAssistant,
    device_id: str,
    *,
    plug_platform: str | None = None,
) -> ResolvedEVDevice:
    """Pick SOC, charge limit, plug/cable, and location entities for a device.

    plug_platform: "tesla" for EV1 (Tesla), "vw" for EV2 (VW / Škoda / SEAT),
    or None for legacy generic scoring.
    """

    registry = er.async_get(hass)
    entries = _entries_for_device(registry, device_id)
    if not entries:
        _LOGGER.warning("No entities on device %s", device_id)
        return ResolvedEVDevice(device_id=device_id)

    def _conn_score(h: HomeAssistant, e: RegistryEntry) -> int:
        return _score_connected(h, e, plug_platform)

    soc_e = _best_entry(hass, entries, _score_soc)
    target_e = _best_entry(hass, entries, _score_target)
    conn_e = _best_entry(hass, entries, _conn_score)
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


def _score_eds_price_entity(hass: HomeAssistant, entry: RegistryEntry) -> int:
    """Prefer Energi Data Service spot sensors (raw_today / raw_tomorrow attributes)."""

    if entry.domain != "sensor":
        return 0
    score = 0
    st = hass.states.get(entry.entity_id)
    if st and isinstance(st.attributes, dict):
        if st.attributes.get("raw_today") is not None:
            score += 100
        if st.attributes.get("raw_tomorrow") is not None:
            score += 40
    oid = entry.entity_id.split(".", 1)[-1].lower()
    for hint in ("elspot", "spot", "price", "electricity", "kwh"):
        if hint in oid:
            score += 5
    return score


def resolve_spot_price_sensor(hass: HomeAssistant, device_id: str) -> str | None:
    """Pick the best sensor on an Energi Data Service device for hourly prices."""

    registry = er.async_get(hass)
    entries = _entries_for_device(registry, device_id)
    best: tuple[int, str] | None = None
    for e in entries:
        s = _score_eds_price_entity(hass, e)
        if s <= 0:
            continue
        cand = (s, e.entity_id)
        if best is None or cand[0] > best[0]:
            best = cand
    if best:
        return best[1]
    for e in entries:
        if e.domain == "sensor":
            return e.entity_id
    return None


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
        if s in (STATE_ON.lower(), "true", "1", "yes", "plugged", "connected"):
            return True
        if s in (STATE_OFF.lower(), "false", "0", "no", "disconnected", "unplugged"):
            return False
        return None
    if domain == "sensor":
        if s in (
            "connected",
            "plugged",
            "plug_connected",
            "on",
            "yes",
            "true",
            "cable_connected",
        ):
            return True
        if s in (
            "disconnected",
            "plug_not_connected",
            "not_connected",
            "off",
            "no",
            "false",
            "cable_disconnected",
        ):
            return False
    return None

"""Constants for homeassistant_ev_auto_smart_charge."""

# Semantic version for HACS / Home Assistant (must match manifest.json "version").
INTEGRATION_VERSION = "0.0.5"

DOMAIN = "homeassistant_ev_auto_smart_charge"

CONF_PRICE_SENSOR = "price_sensor"
# Device-based (v2+)
CONF_EV1_DEVICE_ID = "ev1_device_id"
CONF_EV2_DEVICE_ID = "ev2_device_id"
# Legacy v1 (entity IDs) — migration / fallback
CONF_EV1_SOC_SENSOR = "ev1_soc_sensor"
CONF_EV2_SOC_SENSOR = "ev2_soc_sensor"
CONF_EV1_TARGET_SOC_SENSOR = "ev1_target_soc_sensor"
CONF_EV2_TARGET_SOC_SENSOR = "ev2_target_soc_sensor"
CONF_EV1_HOME_ENTITY = "ev1_home_entity"
CONF_EV2_HOME_ENTITY = "ev2_home_entity"
CONF_CHARGE_PRIORITY = "charge_priority"
CONF_EV1_CAPACITY_KWH = "ev1_capacity_kwh"
CONF_EV2_CAPACITY_KWH = "ev2_capacity_kwh"
CONF_CHARGER_POWER_KW = "charger_power_kw"
CONF_TARGET_SOC_PERCENT = "target_soc_percent"

CHARGE_PRIORITY_EV1_FIRST = "ev1_first"
CHARGE_PRIORITY_EV2_FIRST = "ev2_first"
CHARGE_PRIORITY_BALANCED = "balanced"

# Config flow: device picker filters (integration config entry domains)
TESLA_DEVICE_INTEGRATIONS = (
    "tesla_custom",
    "tesla",
)
VW_FAMILY_DEVICE_INTEGRATIONS = (
    "volkswagencarnet",
    "skodaconnect",
    "seatconnect",
)

DEFAULT_CHARGER_KW = 11.0
DEFAULT_TARGET_SOC = 100.0
DEFAULT_CHARGE_PRIORITY = CHARGE_PRIORITY_BALANCED
DEFAULT_EV1_CAPACITY_KWH = 73.0
DEFAULT_EV2_CAPACITY_KWH = 58.0

UPDATE_INTERVAL_MIN = 5

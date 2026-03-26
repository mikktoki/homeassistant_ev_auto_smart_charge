"""Constants for homeassistant_ev_auto_smart_charge."""

# Semantic version for HACS / Home Assistant (must match manifest.json "version").
INTEGRATION_VERSION = "0.0.11"

DOMAIN = "homeassistant_ev_auto_smart_charge"

CONF_PRICE_SENSOR = "price_sensor"
CONF_PRICE_DEVICE_ID = "price_device_id"
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
CONF_CHARGE_ORDER_MODE = "charge_order_mode"
CONF_EV1_CAPACITY_KWH = "ev1_capacity_kwh"
CONF_EV2_CAPACITY_KWH = "ev2_capacity_kwh"
CONF_CHARGER_POWER_KW = "charger_power_kw"
# Optional Zaptec charger device (custom_components/zaptec) — kW from charger max-current setpoint
CONF_ZAPTEC_CHARGER_DEVICE_ID = "zaptec_charger_device_id"
CONF_TARGET_SOC_PERCENT = "target_soc_percent"
CONF_EV1_DONE_BY = "ev1_done_by"
CONF_EV2_DONE_BY = "ev2_done_by"

CHARGE_PRIORITY_EV1_FIRST = "ev1_first"
CHARGE_PRIORITY_EV2_FIRST = "ev2_first"
CHARGE_PRIORITY_BALANCED = "balanced"
CHARGE_ORDER_MODE_MANUAL = "manual"
CHARGE_ORDER_MODE_ECONOMICAL = "economical"

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
# Energi Data Service (HACS) — hourly spot prices (raw_today / raw_tomorrow)
ENERGI_DATA_SERVICE_INTEGRATIONS = ("energidataservice",)
ZAPTEC_DEVICE_INTEGRATIONS = ("zaptec",)

# Zaptec AC power estimate: kW ≈ I(A) × phases × V(L-N) / 1000 (see integration README / install limits)
ZAPTEC_CALC_PHASES = 3
ZAPTEC_CALC_VOLTAGE_V = 230.0

DEFAULT_CHARGER_KW = 11.0
DEFAULT_TARGET_SOC = 100.0
DEFAULT_CHARGE_PRIORITY = CHARGE_PRIORITY_BALANCED
DEFAULT_CHARGE_ORDER_MODE = CHARGE_ORDER_MODE_MANUAL
DEFAULT_EV1_CAPACITY_KWH = 73.0
DEFAULT_EV2_CAPACITY_KWH = 58.0

UPDATE_INTERVAL_MIN = 5

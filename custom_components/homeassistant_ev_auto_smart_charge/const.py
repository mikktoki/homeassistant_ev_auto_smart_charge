"""Constants for homeassistant_ev_auto_smart_charge."""

DOMAIN = "homeassistant_ev_auto_smart_charge"

CONF_PRICE_SENSOR = "price_sensor"
CONF_EV1_SOC_SENSOR = "ev1_soc_sensor"
CONF_EV2_SOC_SENSOR = "ev2_soc_sensor"
CONF_EV1_CAPACITY_KWH = "ev1_capacity_kwh"
CONF_EV2_CAPACITY_KWH = "ev2_capacity_kwh"
CONF_CHARGER_POWER_KW = "charger_power_kw"
CONF_TARGET_SOC_PERCENT = "target_soc_percent"

DEFAULT_CHARGER_KW = 11.0
DEFAULT_TARGET_SOC = 100.0

UPDATE_INTERVAL_MIN = 5

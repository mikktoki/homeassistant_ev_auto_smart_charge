"""Config flow for homeassistant_ev_auto_smart_charge."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CHARGE_PRIORITY_BALANCED,
    CHARGE_PRIORITY_EV1_FIRST,
    CHARGE_PRIORITY_EV2_FIRST,
    CONF_CHARGER_POWER_KW,
    CONF_CHARGE_PRIORITY,
    CONF_EV1_CAPACITY_KWH,
    CONF_EV1_HOME_ENTITY,
    CONF_EV1_SOC_SENSOR,
    CONF_EV1_TARGET_SOC_SENSOR,
    CONF_EV2_CAPACITY_KWH,
    CONF_EV2_HOME_ENTITY,
    CONF_EV2_SOC_SENSOR,
    CONF_EV2_TARGET_SOC_SENSOR,
    CONF_PRICE_SENSOR,
    CONF_TARGET_SOC_PERCENT,
    DEFAULT_CHARGE_PRIORITY,
    DEFAULT_CHARGER_KW,
    DEFAULT_TARGET_SOC,
    DOMAIN,
)

_TARGET_ENTITY_DOMAINS: list[str] = [SENSOR_DOMAIN, "number", "input_number"]
_HOME_ENTITY_DOMAINS: list[str] = [
    "binary_sensor",
    "device_tracker",
    "person",
    "input_boolean",
]

_OPTIONAL_ENTITY_KEYS = (
    CONF_EV1_TARGET_SOC_SENSOR,
    CONF_EV2_TARGET_SOC_SENSOR,
    CONF_EV1_HOME_ENTITY,
    CONF_EV2_HOME_ENTITY,
)


def _strip_empty_optional_entities(data: Any) -> Any:
    """Entity selectors reject ''; optional fields must omit the key instead."""

    if not isinstance(data, dict):
        return data
    cleaned = dict(data)
    for key in _OPTIONAL_ENTITY_KEYS:
        if cleaned.get(key) in (None, ""):
            cleaned.pop(key, None)
    return cleaned


class _SchemaStripOptionalEntities(vol.Schema):
    """Keep schema.schema as a dict (required by HA form UI); strip '' before submit."""

    def __call__(self, data: Any) -> Any:
        if isinstance(data, dict):
            data = _strip_empty_optional_entities(dict(data))
        return super().__call__(data)


def _user_schema_defaults(data: dict) -> vol.Schema:
    return _SchemaStripOptionalEntities(
        {
            vol.Required(CONF_PRICE_SENSOR, default=data.get(CONF_PRICE_SENSOR, "")): EntitySelector(
                EntitySelectorConfig(domain=SENSOR_DOMAIN)
            ),
            vol.Required(CONF_EV1_SOC_SENSOR, default=data.get(CONF_EV1_SOC_SENSOR, "")): EntitySelector(
                EntitySelectorConfig(domain=SENSOR_DOMAIN)
            ),
            vol.Required(CONF_EV2_SOC_SENSOR, default=data.get(CONF_EV2_SOC_SENSOR, "")): EntitySelector(
                EntitySelectorConfig(domain=SENSOR_DOMAIN)
            ),
            vol.Optional(CONF_EV1_TARGET_SOC_SENSOR): EntitySelector(
                EntitySelectorConfig(domain=_TARGET_ENTITY_DOMAINS)
            ),
            vol.Optional(CONF_EV2_TARGET_SOC_SENSOR): EntitySelector(
                EntitySelectorConfig(domain=_TARGET_ENTITY_DOMAINS)
            ),
            vol.Required(
                CONF_EV1_CAPACITY_KWH,
                default=data.get(CONF_EV1_CAPACITY_KWH, 75.0),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=200,
                    step=0.1,
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_EV2_CAPACITY_KWH,
                default=data.get(CONF_EV2_CAPACITY_KWH, 77.0),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=200,
                    step=0.1,
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_CHARGER_POWER_KW,
                default=data.get(CONF_CHARGER_POWER_KW, DEFAULT_CHARGER_KW),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0.1,
                    max=50,
                    step=0.1,
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_TARGET_SOC_PERCENT,
                default=data.get(CONF_TARGET_SOC_PERCENT, DEFAULT_TARGET_SOC),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=50,
                    max=100,
                    step=1,
                    mode=NumberSelectorMode.SLIDER,
                )
            ),
        }
    )


class EvAutoSmartChargeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle UI setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(
                f"{user_input[CONF_PRICE_SENSOR]}_{user_input[CONF_EV1_SOC_SENSOR]}_{user_input[CONF_EV2_SOC_SENSOR]}"
            )
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="EV Auto Smart Charge",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema_defaults({}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        return EvAutoSmartChargeOptionsFlow(config_entry)


class EvAutoSmartChargeOptionsFlow(OptionsFlow):
    """Adjust capacities, charger power, and target SOC."""

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        merged = {**self.config_entry.data, **self.config_entry.options}
        schema = _SchemaStripOptionalEntities(
            {
                vol.Optional(CONF_EV1_TARGET_SOC_SENSOR): EntitySelector(
                    EntitySelectorConfig(domain=_TARGET_ENTITY_DOMAINS)
                ),
                vol.Optional(CONF_EV2_TARGET_SOC_SENSOR): EntitySelector(
                    EntitySelectorConfig(domain=_TARGET_ENTITY_DOMAINS)
                ),
                vol.Optional(CONF_EV1_HOME_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain=_HOME_ENTITY_DOMAINS)
                ),
                vol.Optional(CONF_EV2_HOME_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain=_HOME_ENTITY_DOMAINS)
                ),
                vol.Required(
                    CONF_CHARGE_PRIORITY,
                    default=merged.get(
                        CONF_CHARGE_PRIORITY, DEFAULT_CHARGE_PRIORITY
                    ),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            {
                                "value": CHARGE_PRIORITY_EV1_FIRST,
                                "label": "EV 1 first",
                            },
                            {
                                "value": CHARGE_PRIORITY_EV2_FIRST,
                                "label": "EV 2 first",
                            },
                            {
                                "value": CHARGE_PRIORITY_BALANCED,
                                "label": "Balanced (by kWh)",
                            },
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_EV1_CAPACITY_KWH,
                    default=merged.get(CONF_EV1_CAPACITY_KWH, 75.0),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=200,
                        step=0.1,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_EV2_CAPACITY_KWH,
                    default=merged.get(CONF_EV2_CAPACITY_KWH, 77.0),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=200,
                        step=0.1,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_CHARGER_POWER_KW,
                    default=merged.get(CONF_CHARGER_POWER_KW, DEFAULT_CHARGER_KW),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.1,
                        max=50,
                        step=0.1,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_TARGET_SOC_PERCENT,
                    default=merged.get(CONF_TARGET_SOC_PERCENT, DEFAULT_TARGET_SOC),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=50,
                        max=100,
                        step=1,
                        mode=NumberSelectorMode.SLIDER,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)

"""Config flow for homeassistant_ev_auto_smart_charge."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    DeviceSelector,
    DeviceSelectorConfig,
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
    CONF_EV1_DEVICE_ID,
    CONF_EV2_CAPACITY_KWH,
    CONF_EV2_DEVICE_ID,
    CONF_PRICE_DEVICE_ID,
    CONF_TARGET_SOC_PERCENT,
    CONF_ZAPTEC_CHARGER_DEVICE_ID,
    ENERGI_DATA_SERVICE_INTEGRATIONS,
    DEFAULT_CHARGE_PRIORITY,
    DEFAULT_CHARGER_KW,
    DEFAULT_EV1_CAPACITY_KWH,
    DEFAULT_EV2_CAPACITY_KWH,
    DEFAULT_TARGET_SOC,
    DOMAIN,
    TESLA_DEVICE_INTEGRATIONS,
    VW_FAMILY_DEVICE_INTEGRATIONS,
    ZAPTEC_DEVICE_INTEGRATIONS,
)


def _tesla_device_filter() -> list[dict[str, str]]:
    return [{"integration": d} for d in TESLA_DEVICE_INTEGRATIONS]


def _vw_family_device_filter() -> list[dict[str, str]]:
    return [{"integration": dom} for dom in VW_FAMILY_DEVICE_INTEGRATIONS]


def _energi_device_filter() -> list[dict[str, str]]:
    return [{"integration": dom} for dom in ENERGI_DATA_SERVICE_INTEGRATIONS]


def _zaptec_device_filter() -> list[dict[str, str]]:
    return [{"integration": dom} for dom in ZAPTEC_DEVICE_INTEGRATIONS]


def _user_schema(data: dict) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_PRICE_DEVICE_ID,
                default=data.get(CONF_PRICE_DEVICE_ID),
            ): DeviceSelector(
                DeviceSelectorConfig(filter=_energi_device_filter())
            ),
            vol.Required(
                CONF_EV1_DEVICE_ID,
                default=data.get(CONF_EV1_DEVICE_ID),
            ): DeviceSelector(
                DeviceSelectorConfig(filter=_tesla_device_filter())
            ),
            vol.Required(
                CONF_EV2_DEVICE_ID,
                default=data.get(CONF_EV2_DEVICE_ID),
            ): DeviceSelector(
                DeviceSelectorConfig(filter=_vw_family_device_filter())
            ),
            vol.Required(
                CONF_EV1_CAPACITY_KWH,
                default=data.get(CONF_EV1_CAPACITY_KWH, DEFAULT_EV1_CAPACITY_KWH),
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
                default=data.get(CONF_EV2_CAPACITY_KWH, DEFAULT_EV2_CAPACITY_KWH),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=200,
                    step=0.1,
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_ZAPTEC_CHARGER_DEVICE_ID,
                default=data.get(CONF_ZAPTEC_CHARGER_DEVICE_ID),
            ): DeviceSelector(
                DeviceSelectorConfig(filter=_zaptec_device_filter())
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

    VERSION = 3

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            zid = user_input.get(CONF_ZAPTEC_CHARGER_DEVICE_ID) or ""
            uid = (
                f"{user_input[CONF_PRICE_DEVICE_ID]}_"
                f"{user_input[CONF_EV1_DEVICE_ID]}_"
                f"{user_input[CONF_EV2_DEVICE_ID]}"
            )
            if zid:
                uid = f"{uid}_{zid}"
            await self.async_set_unique_id(uid)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="EV Auto Smart Charge",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema({}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        return EvAutoSmartChargeOptionsFlow(config_entry)


class EvAutoSmartChargeOptionsFlow(OptionsFlow):
    """Adjust capacities, charger power, charge order, and target fallback."""

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        merged = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema(
            {
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
                                "label": "EV 1 (Tesla) first",
                            },
                            {
                                "value": CHARGE_PRIORITY_EV2_FIRST,
                                "label": "EV 2 (VW family) first",
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
                    default=merged.get(
                        CONF_EV1_CAPACITY_KWH, DEFAULT_EV1_CAPACITY_KWH
                    ),
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
                    default=merged.get(
                        CONF_EV2_CAPACITY_KWH, DEFAULT_EV2_CAPACITY_KWH
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=200,
                        step=0.1,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_ZAPTEC_CHARGER_DEVICE_ID,
                    default=merged.get(CONF_ZAPTEC_CHARGER_DEVICE_ID),
                ): DeviceSelector(
                    DeviceSelectorConfig(filter=_zaptec_device_filter())
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

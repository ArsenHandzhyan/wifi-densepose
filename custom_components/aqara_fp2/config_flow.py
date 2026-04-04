"""Config flow for Aqara FP2 integration."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_APP_ID,
    CONF_APP_KEY,
    CONF_DEVICE_ID,
    CONF_KEY_ID,
    CONF_REFRESH_TOKEN,
    CONF_REGION,
    API_DOMAINS,
    DEFAULT_APP_ID,
    DEFAULT_APP_KEY,
    DEFAULT_KEY_ID,
    DEFAULT_REGION,
    DOMAIN,
)


class AqaraFp2ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Aqara FP2."""

    VERSION = 2

    def __init__(self):
        """Initialize the config flow."""
        self._data = {}

    async def async_step_user(self, user_input=None):
        """Handle the initial step — region and credentials."""
        errors = {}

        if user_input is not None:
            if not user_input.get(CONF_ACCESS_TOKEN):
                errors["base"] = "access_token_required"
            elif not user_input.get(CONF_DEVICE_ID):
                errors["base"] = "device_id_required"
            else:
                await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Aqara FP2 ({user_input[CONF_REGION]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_REGION, default=DEFAULT_REGION): vol.In(
                        API_DOMAINS
                    ),
                    vol.Required(CONF_ACCESS_TOKEN): str,
                    vol.Optional(CONF_REFRESH_TOKEN): str,
                    vol.Optional(CONF_APP_ID, default=DEFAULT_APP_ID): str,
                    vol.Optional(CONF_APP_KEY, default=DEFAULT_APP_KEY): str,
                    vol.Optional(CONF_KEY_ID, default=DEFAULT_KEY_ID): str,
                    vol.Required(CONF_DEVICE_ID): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow — allows changing region and updating tokens."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_REGION,
                        default=self.config_entry.data.get(
                            CONF_REGION, DEFAULT_REGION
                        ),
                    ): vol.In(API_DOMAINS),
                    vol.Optional(
                        CONF_ACCESS_TOKEN,
                        description={
                            "suggested_value": self.config_entry.data.get(
                                CONF_ACCESS_TOKEN, ""
                            )
                        },
                    ): str,
                    vol.Optional(
                        CONF_REFRESH_TOKEN,
                        description={
                            "suggested_value": self.config_entry.data.get(
                                CONF_REFRESH_TOKEN, ""
                            )
                        },
                    ): str,
                    vol.Optional(
                        CONF_APP_ID,
                        description={
                            "suggested_value": self.config_entry.options.get(
                                CONF_APP_ID,
                                self.config_entry.data.get(CONF_APP_ID, DEFAULT_APP_ID),
                            )
                        },
                    ): str,
                    vol.Optional(
                        CONF_APP_KEY,
                        description={
                            "suggested_value": self.config_entry.options.get(
                                CONF_APP_KEY,
                                self.config_entry.data.get(CONF_APP_KEY, DEFAULT_APP_KEY),
                            )
                        },
                    ): str,
                    vol.Optional(
                        CONF_KEY_ID,
                        description={
                            "suggested_value": self.config_entry.options.get(
                                CONF_KEY_ID,
                                self.config_entry.data.get(CONF_KEY_ID, DEFAULT_KEY_ID),
                            )
                        },
                    ): str,
                }
            ),
        )

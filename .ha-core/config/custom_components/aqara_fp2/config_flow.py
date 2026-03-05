"""Config flow for Aqara FP2 integration."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .const import DOMAIN, API_DOMAINS, DEFAULT_REGION, CONF_REGION, CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN


class AqaraFp2ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Aqara FP2."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._data = {}

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            self._data.update(user_input)
            
            # Validate credentials (basic validation)
            if not user_input.get(CONF_ACCESS_TOKEN):
                errors["base"] = "access_token_required"
            else:
                # Create entry
                return self.async_create_entry(
                    title=f"Aqara FP2 ({user_input[CONF_REGION]})",
                    data=self._data
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_REGION, default=DEFAULT_REGION): vol.In(API_DOMAINS),
                vol.Required(CONF_ACCESS_TOKEN): str,
                vol.Optional(CONF_REFRESH_TOKEN): str,
            }),
            errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_REGION,
                    default=self.config_entry.data.get(CONF_REGION, DEFAULT_REGION)
                ): vol.In(API_DOMAINS),
            })
        )

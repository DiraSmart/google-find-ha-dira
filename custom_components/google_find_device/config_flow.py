"""Config flow for Google Find My Device integration."""

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .api import AuthenticationError, GoogleFindDeviceAPI
from .const import CONF_APP_PASSWORD, CONF_EMAIL, CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_APP_PASSWORD): str,
        vol.Optional(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL): vol.All(
            int, vol.Range(min=60, max=3600)
        ),
    }
)


async def _validate_credentials(hass: HomeAssistant, email: str, app_password: str) -> bool:
    """Validate Google credentials by attempting authentication."""
    api = GoogleFindDeviceAPI(email, app_password)
    await api.authenticate(hass)
    return True


class GoogleFindDeviceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Google Find My Device."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step - user provides credentials."""
        errors = {}

        if user_input is not None:
            try:
                await _validate_credentials(
                    self.hass,
                    user_input[CONF_EMAIL],
                    user_input[CONF_APP_PASSWORD],
                )
            except AuthenticationError as err:
                _LOGGER.error("Authentication failed: %s", err)
                errors["base"] = "invalid_auth"
            except Exception as err:
                _LOGGER.exception("Unexpected error during setup: %s", err)
                errors["base"] = "unknown"
            else:
                # Check if already configured with this email
                await self.async_set_unique_id(user_input[CONF_EMAIL])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Google Find My Device ({user_input[CONF_EMAIL]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

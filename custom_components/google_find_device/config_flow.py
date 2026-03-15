"""Config flow for Google Find My Device integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .api import AuthenticationError, GoogleFindDeviceAPI
from .const import (
    CONF_APP_PASSWORD,
    CONF_AUTH_METHOD,
    CONF_EMAIL,
    CONF_MASTER_TOKEN,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

AUTH_METHOD_APP_PASSWORD = "app_password"
AUTH_METHOD_MASTER_TOKEN = "master_token"


class GoogleFindDeviceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Google Find My Device."""

    VERSION = 1

    def __init__(self) -> None:
        self._auth_method: str | None = None

    async def async_step_user(self, user_input=None):
        """Step 1: Choose authentication method."""
        if user_input is not None:
            self._auth_method = user_input[CONF_AUTH_METHOD]
            if self._auth_method == AUTH_METHOD_APP_PASSWORD:
                return await self.async_step_app_password()
            return await self.async_step_master_token()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AUTH_METHOD, default=AUTH_METHOD_MASTER_TOKEN): vol.In(
                        {
                            AUTH_METHOD_MASTER_TOKEN: "Master Token (recommended)",
                            AUTH_METHOD_APP_PASSWORD: "App Password (may not work)",
                        }
                    ),
                }
            ),
        )

    async def async_step_app_password(self, user_input=None):
        """Step 2a: Email + App Password."""
        errors = {}

        if user_input is not None:
            try:
                api = GoogleFindDeviceAPI(
                    email=user_input[CONF_EMAIL],
                    app_password=user_input[CONF_APP_PASSWORD],
                )
                await api.authenticate(self.hass)
            except AuthenticationError as err:
                _LOGGER.error("Authentication failed: %s", err)
                errors["base"] = "invalid_auth"
            except Exception as err:
                _LOGGER.exception("Unexpected error: %s", err)
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_EMAIL])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Google Find My Device ({user_input[CONF_EMAIL]})",
                    data={
                        CONF_AUTH_METHOD: AUTH_METHOD_APP_PASSWORD,
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_APP_PASSWORD: user_input[CONF_APP_PASSWORD],
                        CONF_POLL_INTERVAL: user_input.get(
                            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                        ),
                    },
                )

        return self.async_show_form(
            step_id="app_password",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_APP_PASSWORD): str,
                    vol.Optional(
                        CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL
                    ): vol.All(int, vol.Range(min=60, max=3600)),
                }
            ),
            errors=errors,
        )

    async def async_step_master_token(self, user_input=None):
        """Step 2b: Email + Master Token."""
        errors = {}

        if user_input is not None:
            try:
                api = GoogleFindDeviceAPI(
                    email=user_input[CONF_EMAIL],
                    master_token=user_input[CONF_MASTER_TOKEN],
                )
                await api.authenticate(self.hass)
            except AuthenticationError as err:
                _LOGGER.error("Authentication failed: %s", err)
                errors["base"] = "invalid_auth"
            except Exception as err:
                _LOGGER.exception("Unexpected error: %s", err)
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_EMAIL])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Google Find My Device ({user_input[CONF_EMAIL]})",
                    data={
                        CONF_AUTH_METHOD: AUTH_METHOD_MASTER_TOKEN,
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_MASTER_TOKEN: user_input[CONF_MASTER_TOKEN],
                        CONF_POLL_INTERVAL: user_input.get(
                            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                        ),
                    },
                )

        return self.async_show_form(
            step_id="master_token",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_MASTER_TOKEN): str,
                    vol.Optional(
                        CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL
                    ): vol.All(int, vol.Range(min=60, max=3600)),
                }
            ),
            errors=errors,
        )

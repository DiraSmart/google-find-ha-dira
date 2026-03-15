"""Google Find My Device integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .api import AuthenticationError, GoogleFindDeviceAPI
from .const import (
    CONF_APP_PASSWORD,
    CONF_AUTH_METHOD,
    CONF_EMAIL,
    CONF_MASTER_TOKEN,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import GoogleFindDeviceCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Google Find My Device from a config entry."""
    email = entry.data[CONF_EMAIL]
    poll_interval = entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    auth_method = entry.data.get(CONF_AUTH_METHOD, "app_password")

    if auth_method == "master_token":
        api = GoogleFindDeviceAPI(
            email=email,
            master_token=entry.data[CONF_MASTER_TOKEN],
        )
    else:
        api = GoogleFindDeviceAPI(
            email=email,
            app_password=entry.data.get(CONF_APP_PASSWORD),
        )

    try:
        await api.authenticate(hass)
    except AuthenticationError as err:
        raise ConfigEntryNotReady(f"Authentication failed: {err}") from err
    except Exception as err:
        raise ConfigEntryNotReady(f"Setup failed: {err}") from err

    coordinator = GoogleFindDeviceCoordinator(hass, api, poll_interval)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

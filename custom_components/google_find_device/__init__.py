"""Google Find My Device integration for Home Assistant."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import GoogleFindDeviceAPI
from .const import CONF_APP_PASSWORD, CONF_EMAIL, CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, DOMAIN, PLATFORMS
from .coordinator import GoogleFindDeviceCoordinator

_LOGGER = logging.getLogger(__name__)

type GoogleFindDeviceConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: GoogleFindDeviceConfigEntry) -> bool:
    """Set up Google Find My Device from a config entry."""
    email = entry.data[CONF_EMAIL]
    app_password = entry.data[CONF_APP_PASSWORD]
    poll_interval = entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)

    api = GoogleFindDeviceAPI(email, app_password)

    try:
        await api.authenticate(hass)
    except Exception as err:
        _LOGGER.error("Failed to authenticate with Google: %s", err)
        raise

    coordinator = GoogleFindDeviceCoordinator(hass, api, poll_interval)

    # Initial data fetch
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: GoogleFindDeviceConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok

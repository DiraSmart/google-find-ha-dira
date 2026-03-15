"""Data coordinator for Google Find My Device integration."""

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import APIError, AuthenticationError, GoogleFindDeviceAPI
from .const import DEFAULT_POLL_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class GoogleFindDeviceCoordinator(DataUpdateCoordinator):
    """Coordinator to manage fetching device data from Google."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: GoogleFindDeviceAPI,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
    ):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=poll_interval),
        )
        self.api = api
        self._auth_failures = 0
        self._max_auth_retries = 3

    async def _async_update_data(self) -> dict:
        """Fetch device data from Google Find My Device API."""
        try:
            devices = await self.api.list_devices(self.hass)
            self._auth_failures = 0
            return devices

        except AuthenticationError as err:
            self._auth_failures += 1
            _LOGGER.warning(
                "Authentication error (attempt %d/%d): %s",
                self._auth_failures,
                self._max_auth_retries,
                err,
            )

            if self._auth_failures <= self._max_auth_retries:
                try:
                    await self.api.authenticate(self.hass)
                    devices = await self.api.list_devices(self.hass)
                    self._auth_failures = 0
                    return devices
                except Exception as retry_err:
                    raise UpdateFailed(
                        f"Re-authentication failed: {retry_err}"
                    ) from retry_err

            raise UpdateFailed(
                f"Authentication failed after {self._max_auth_retries} retries: {err}"
            ) from err

        except APIError as err:
            raise UpdateFailed(f"API error: {err}") from err

        except Exception as err:
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def async_ring_device(self, device_id: str, device_type: int = 1) -> bool:
        """Ring a device."""
        return await self.api.ring_device(self.hass, device_id, device_type)

    async def async_stop_sound(self, device_id: str, device_type: int = 1) -> bool:
        """Stop sound on a device."""
        return await self.api.stop_sound_device(self.hass, device_id, device_type)

    async def async_locate_device(self, device_id: str, device_type: int = 1) -> bool:
        """Request fresh location for a device."""
        result = await self.api.locate_device(self.hass, device_id, device_type)
        if result:
            # Schedule a refresh to get the updated location
            await self.async_request_refresh()
        return result

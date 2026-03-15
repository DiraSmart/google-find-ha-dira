"""Button platform for Google Find My Device - Ring and Locate actions."""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GoogleFindDeviceCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities for ring and locate."""
    coordinator: GoogleFindDeviceCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    if coordinator.data:
        for device_id, device_info in coordinator.data.items():
            device_type = device_info.get("device_type", 1)
            entities.append(
                GoogleFindDeviceRingButton(coordinator, device_id, device_info, device_type)
            )
            entities.append(
                GoogleFindDeviceStopSoundButton(coordinator, device_id, device_info, device_type)
            )
            entities.append(
                GoogleFindDeviceLocateButton(coordinator, device_id, device_info, device_type)
            )

    async_add_entities(entities, True)

    # Track new devices
    known_devices = set(coordinator.data.keys()) if coordinator.data else set()

    @callback
    def _check_new_devices():
        if not coordinator.data:
            return

        new_devices = set(coordinator.data.keys()) - known_devices
        if new_devices:
            new_entities = []
            for device_id in new_devices:
                device_info = coordinator.data[device_id]
                device_type = device_info.get("device_type", 1)
                new_entities.extend([
                    GoogleFindDeviceRingButton(coordinator, device_id, device_info, device_type),
                    GoogleFindDeviceStopSoundButton(coordinator, device_id, device_info, device_type),
                    GoogleFindDeviceLocateButton(coordinator, device_id, device_info, device_type),
                ])
                known_devices.add(device_id)

            if new_entities:
                async_add_entities(new_entities, True)

    coordinator.async_add_listener(_check_new_devices)


class GoogleFindDeviceRingButton(CoordinatorEntity, ButtonEntity):
    """Button to ring a device."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:bell-ring"

    def __init__(self, coordinator, device_id, device_info, device_type):
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_type = device_type
        self._attr_unique_id = f"google_find_{device_id}_ring"
        self._attr_name = f"{device_info.get('name', 'Device')} - Ring"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
        }

    async def async_press(self) -> None:
        """Ring the device."""
        _LOGGER.info("Ringing device %s", self._device_id)
        success = await self.coordinator.async_ring_device(
            self._device_id, self._device_type
        )
        if not success:
            _LOGGER.warning("Failed to ring device %s", self._device_id)


class GoogleFindDeviceStopSoundButton(CoordinatorEntity, ButtonEntity):
    """Button to stop sound on a device."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:bell-off"

    def __init__(self, coordinator, device_id, device_info, device_type):
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_type = device_type
        self._attr_unique_id = f"google_find_{device_id}_stop_sound"
        self._attr_name = f"{device_info.get('name', 'Device')} - Stop Sound"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
        }

    async def async_press(self) -> None:
        """Stop sound on the device."""
        _LOGGER.info("Stopping sound on device %s", self._device_id)
        success = await self.coordinator.async_stop_sound(
            self._device_id, self._device_type
        )
        if not success:
            _LOGGER.warning("Failed to stop sound on device %s", self._device_id)


class GoogleFindDeviceLocateButton(CoordinatorEntity, ButtonEntity):
    """Button to request fresh location for a device."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:crosshairs-gps"

    def __init__(self, coordinator, device_id, device_info, device_type):
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_type = device_type
        self._attr_unique_id = f"google_find_{device_id}_locate"
        self._attr_name = f"{device_info.get('name', 'Device')} - Locate"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
        }

    async def async_press(self) -> None:
        """Request fresh location for the device."""
        _LOGGER.info("Requesting location for device %s", self._device_id)
        success = await self.coordinator.async_locate_device(
            self._device_id, self._device_type
        )
        if not success:
            _LOGGER.warning("Failed to locate device %s", self._device_id)

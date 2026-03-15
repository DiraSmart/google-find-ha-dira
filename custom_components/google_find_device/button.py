"""Button platform for Google Find My Device - Ring and Locate actions."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
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
            entities.extend([
                GoogleFindDeviceRingButton(coordinator, device_id, device_info, device_type),
                GoogleFindDeviceStopSoundButton(coordinator, device_id, device_info, device_type),
                GoogleFindDeviceLocateButton(coordinator, device_id, device_info, device_type),
            ])

    async_add_entities(entities, True)

    known_devices = set(coordinator.data.keys()) if coordinator.data else set()

    @callback
    def _check_new_devices():
        if not coordinator.data:
            return

        new_devices = set(coordinator.data.keys()) - known_devices
        if new_devices:
            new_entities = []
            for device_id in new_devices:
                info = coordinator.data[device_id]
                dt = info.get("device_type", 1)
                new_entities.extend([
                    GoogleFindDeviceRingButton(coordinator, device_id, info, dt),
                    GoogleFindDeviceStopSoundButton(coordinator, device_id, info, dt),
                    GoogleFindDeviceLocateButton(coordinator, device_id, info, dt),
                ])
                known_devices.add(device_id)

            if new_entities:
                async_add_entities(new_entities, True)

    coordinator.async_add_listener(_check_new_devices)


class GoogleFindDeviceRingButton(CoordinatorEntity, ButtonEntity):
    """Button to ring a device."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:bell-ring"

    def __init__(self, coordinator, device_id, device_info, device_type) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_type = device_type
        self._attr_unique_id = f"google_find_{device_id}_ring"
        self._attr_name = f"{device_info.get('name', 'Device')} - Ring"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
        )

    async def async_press(self) -> None:
        await self.coordinator.async_ring_device(self._device_id, self._device_type)


class GoogleFindDeviceStopSoundButton(CoordinatorEntity, ButtonEntity):
    """Button to stop sound on a device."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:bell-off"

    def __init__(self, coordinator, device_id, device_info, device_type) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_type = device_type
        self._attr_unique_id = f"google_find_{device_id}_stop_sound"
        self._attr_name = f"{device_info.get('name', 'Device')} - Stop Sound"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
        )

    async def async_press(self) -> None:
        await self.coordinator.async_stop_sound(self._device_id, self._device_type)


class GoogleFindDeviceLocateButton(CoordinatorEntity, ButtonEntity):
    """Button to request fresh location for a device."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:crosshairs-gps"

    def __init__(self, coordinator, device_id, device_info, device_type) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_type = device_type
        self._attr_unique_id = f"google_find_{device_id}_locate"
        self._attr_name = f"{device_info.get('name', 'Device')} - Locate"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
        )

    async def async_press(self) -> None:
        await self.coordinator.async_locate_device(self._device_id, self._device_type)

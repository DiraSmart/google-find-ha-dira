"""Device tracker platform for Google Find My Device."""

from __future__ import annotations

import logging

from homeassistant.components.device_tracker import SourceType, TrackerEntity
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
    """Set up device tracker entities."""
    coordinator: GoogleFindDeviceCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    if coordinator.data:
        for device_id, device_info in coordinator.data.items():
            entities.append(
                GoogleFindDeviceTracker(coordinator, device_id, device_info)
            )

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
                new_entities.append(
                    GoogleFindDeviceTracker(coordinator, device_id, info)
                )
                known_devices.add(device_id)

            if new_entities:
                async_add_entities(new_entities, True)

    coordinator.async_add_listener(_check_new_devices)


class GoogleFindDeviceTracker(CoordinatorEntity, TrackerEntity):
    """Represents a Google Find My Device device tracker."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GoogleFindDeviceCoordinator,
        device_id: str,
        device_info: dict,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_info = device_info
        self._attr_unique_id = f"google_find_{device_id}"
        self._attr_name = device_info.get("name", "Unknown Device")
        device_type_str = "Android" if device_info.get("device_type") == 1 else "Tracker"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_info.get("name", "Unknown Device"),
            manufacturer="Google",
            model=device_info.get("model", device_type_str),
        )

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        if self.coordinator.data and self._device_id in self.coordinator.data:
            return self.coordinator.data[self._device_id].get("latitude")
        return self._device_info.get("latitude")

    @property
    def longitude(self) -> float | None:
        if self.coordinator.data and self._device_id in self.coordinator.data:
            return self.coordinator.data[self._device_id].get("longitude")
        return self._device_info.get("longitude")

    @property
    def location_accuracy(self) -> int:
        accuracy = None
        if self.coordinator.data and self._device_id in self.coordinator.data:
            accuracy = self.coordinator.data[self._device_id].get("accuracy")
        if accuracy is None:
            accuracy = self._device_info.get("accuracy", 0)
        return int(accuracy) if accuracy else 0

    @property
    def battery_level(self) -> int | None:
        if self.coordinator.data and self._device_id in self.coordinator.data:
            return self.coordinator.data[self._device_id].get("battery")
        return self._device_info.get("battery")

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {
            "device_id": self._device_id,
            "device_type": self._device_info.get("device_type", "unknown"),
        }
        if self.coordinator.data and self._device_id in self.coordinator.data:
            data = self.coordinator.data[self._device_id]
            if data.get("last_update"):
                attrs["last_update"] = data["last_update"]
            if data.get("model"):
                attrs["model"] = data["model"]
        return attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.coordinator.data and self._device_id in self.coordinator.data:
            self._device_info = self.coordinator.data[self._device_id]
        self.async_write_ha_state()

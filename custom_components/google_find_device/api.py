"""Google Find My Device API client.

Handles authentication (GCM checkin + Google auth) and Nova API calls
for listing devices, ringing, and locating.
"""

from __future__ import annotations

import binascii
import logging
import time

import aiohttp

from .const import (
    ADM_CERT_SHA1,
    ADM_PACKAGE,
    ADM_SERVICE,
    GCM_CHECKIN_URL,
    NOVA_EXECUTE_ACTION,
    NOVA_HEADERS_BASE,
    NOVA_LIST_DEVICES,
)
from .google_auth import perform_master_login, perform_oauth
from .proto import (
    build_checkin_request,
    build_execute_action_request,
    build_list_devices_request,
    decode_protobuf,
    decode_recursive,
)

_LOGGER = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication fails."""


class APIError(Exception):
    """Raised when an API call fails."""


class GoogleFindDeviceAPI:
    """Client for Google Find My Device using Nova API.

    Supports two auth modes:
    1. Email + App Password (may be blocked by Google)
    2. Email + Master Token (obtained via helper script)
    """

    def __init__(
        self,
        email: str,
        app_password: str | None = None,
        master_token: str | None = None,
    ) -> None:
        self.email = email
        self.app_password = app_password
        self.master_token = master_token
        self.android_id: int | None = None
        self.security_token: int | None = None
        self.gcm_token: str = ""
        self.adm_token: str | None = None
        self.token_expiry: float = 0
        self.devices: dict = {}

    async def authenticate(self, hass) -> bool:
        """Full authentication flow."""
        _LOGGER.debug("Starting authentication flow for %s", self.email)

        # Step 1: GCM Checkin to get android_id
        await self._gcm_checkin()
        _LOGGER.debug("GCM checkin successful, android_id=%s", self.android_id)

        # Step 2: Get ADM token
        if self.master_token:
            # Master token mode - skip master login, go straight to OAuth
            await self._get_adm_token_from_master()
        else:
            # App password mode - do master login first
            await self._get_adm_token_from_password()

        _LOGGER.info("Authentication successful for %s", self.email)
        return True

    async def _gcm_checkin(self) -> None:
        """Perform GCM checkin to get android_id and security_token."""
        checkin_data = build_checkin_request()

        async with aiohttp.ClientSession() as session:
            async with session.post(
                GCM_CHECKIN_URL,
                data=checkin_data,
                headers={"Content-Type": "application/x-protobuf"},
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise AuthenticationError(
                        f"GCM checkin failed (HTTP {resp.status}): {text}"
                    )
                response_data = await resp.read()

        fields = decode_protobuf(response_data)

        android_id_values = fields.get(7, [])
        if not android_id_values:
            raise AuthenticationError("GCM checkin: missing android_id")
        self.android_id = android_id_values[0]

        security_token_values = fields.get(11, [])
        if security_token_values:
            self.security_token = security_token_values[0]

    async def _get_adm_token_from_master(self) -> None:
        """Get ADM token using a pre-obtained master token."""
        android_id_hex = format(self.android_id, "x")

        oauth_resp = await perform_oauth(
            self.email,
            self.master_token,
            android_id_hex,
            ADM_SERVICE,
            ADM_PACKAGE,
            ADM_CERT_SHA1,
        )

        if "Auth" not in oauth_resp:
            error = oauth_resp.get("Error", "Unknown error")
            raise AuthenticationError(f"OAuth failed: {error}")

        self.adm_token = oauth_resp["Auth"]
        self.token_expiry = time.time() + 3500
        _LOGGER.debug("ADM token obtained from master token")

    async def _get_adm_token_from_password(self) -> None:
        """Get ADM token using email + app password."""
        android_id_hex = format(self.android_id, "x")

        # Master login
        master_resp = await perform_master_login(
            self.email,
            self.app_password,
            android_id_hex,
        )

        if "Token" not in master_resp:
            error = master_resp.get("Error", "Unknown error")
            raise AuthenticationError(f"Google login failed: {error}")

        self.master_token = master_resp["Token"]
        _LOGGER.debug("Master login successful")

        # Get ADM token
        await self._get_adm_token_from_master()

    async def refresh_token_if_needed(self, hass) -> None:
        """Refresh the ADM token if expired."""
        if time.time() > self.token_expiry:
            _LOGGER.debug("ADM token expired, refreshing...")
            await self._get_adm_token_from_master()

    def _nova_headers(self) -> dict:
        headers = dict(NOVA_HEADERS_BASE)
        headers["Authorization"] = f"Bearer {self.adm_token}"
        return headers

    async def _nova_request(self, endpoint: str, payload: bytes) -> bytes:
        """Make a request to the Nova API."""
        hex_payload = binascii.hexlify(payload).decode("utf-8")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                endpoint,
                data=hex_payload,
                headers=self._nova_headers(),
            ) as resp:
                if resp.status == 401:
                    raise AuthenticationError("ADM token expired or invalid")
                if resp.status != 200:
                    text = await resp.text()
                    raise APIError(
                        f"Nova API error (HTTP {resp.status}): {text}"
                    )
                response_hex = await resp.text()

        try:
            return binascii.unhexlify(response_hex.strip())
        except (ValueError, binascii.Error):
            return response_hex.encode()

    async def list_devices(self, hass) -> dict:
        """List all devices via Nova API."""
        await self.refresh_token_if_needed(hass)

        all_devices = {}

        for device_type, type_name in [(1, "Android"), (2, "Spot")]:
            try:
                payload = build_list_devices_request(device_type)
                response_data = await self._nova_request(NOVA_LIST_DEVICES, payload)

                if not response_data:
                    continue

                devices = self._parse_device_list(response_data, device_type)
                all_devices.update(devices)
                _LOGGER.debug("Found %d %s device(s)", len(devices), type_name)

            except APIError as err:
                _LOGGER.warning("Error listing %s devices: %s", type_name, err)
            except Exception as err:
                _LOGGER.warning("Error listing %s devices: %s", type_name, err)

        self.devices = all_devices
        return all_devices

    def _parse_device_list(self, data: bytes, device_type: int) -> dict:
        decoded = decode_recursive(data, max_depth=8)
        devices = {}

        if not isinstance(decoded, dict):
            _LOGGER.warning("Failed to decode device list response")
            return devices

        device_entries = decoded.get(2, [])
        if not isinstance(device_entries, list):
            device_entries = [device_entries]

        for entry in device_entries:
            if not isinstance(entry, dict):
                continue
            device_info = self._parse_device_metadata(entry, device_type)
            if device_info and device_info.get("id"):
                devices[device_info["id"]] = device_info

        return devices

    def _parse_device_metadata(self, entry: dict, device_type: int) -> dict | None:
        device_info = {
            "id": None,
            "name": "Unknown Device",
            "model": "",
            "device_type": device_type,
            "latitude": None,
            "longitude": None,
            "accuracy": None,
            "battery": None,
            "last_update": None,
        }

        name = self._find_string_field(entry)
        if name:
            device_info["name"] = name

        device_id = self._find_device_id(entry)
        if device_id:
            device_info["id"] = device_id

        location = self._find_location(entry)
        if location:
            device_info.update(location)

        if not device_info["id"]:
            _LOGGER.debug("Could not extract device ID from: %s", entry)

        return device_info

    def _find_string_field(self, data: dict) -> str | None:
        for value in data.values():
            if isinstance(value, str) and len(value) > 1:
                return value
            if isinstance(value, list):
                for v in value:
                    if isinstance(v, str) and len(v) > 1:
                        return v
        return None

    def _find_device_id(self, data: dict) -> str | None:
        def _search(d, depth=0):
            if depth > 6 or not isinstance(d, dict):
                return None
            for value in d.values():
                if isinstance(value, str) and len(value) > 10 and not value.startswith("http"):
                    return value
                if isinstance(value, dict):
                    result = _search(value, depth + 1)
                    if result:
                        return result
                if isinstance(value, list):
                    for v in value:
                        if isinstance(v, str) and len(v) > 10:
                            return v
                        if isinstance(v, dict):
                            result = _search(v, depth + 1)
                            if result:
                                return result
            return None
        return _search(data)

    def _find_location(self, data: dict) -> dict | None:
        def _search(d, depth=0):
            if depth > 8 or not isinstance(d, dict):
                return None
            f1 = d.get(1)
            f2 = d.get(2)
            f3 = d.get(3)
            if isinstance(f1, (int, float)) and isinstance(f2, (int, float)):
                lat, lon = f1, f2
                if abs(lat) > 1000000:
                    lat, lon = lat / 1e7, lon / 1e7
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    result = {"latitude": lat, "longitude": lon}
                    if isinstance(f3, (int, float)):
                        result["accuracy"] = f3
                    return result
            for value in d.values():
                if isinstance(value, dict):
                    result = _search(value, depth + 1)
                    if result:
                        return result
                elif isinstance(value, list):
                    for v in value:
                        if isinstance(v, dict):
                            result = _search(v, depth + 1)
                            if result:
                                return result
            return None
        return _search(data)

    async def ring_device(self, hass, device_id: str, device_type: int = 1) -> bool:
        await self.refresh_token_if_needed(hass)
        try:
            payload = build_execute_action_request(
                device_type=device_type,
                device_canonic_id=device_id,
                action="ring",
                gcm_token=self.gcm_token,
            )
            await self._nova_request(NOVA_EXECUTE_ACTION, payload)
            return True
        except Exception as err:
            _LOGGER.error("Failed to ring device %s: %s", device_id, err)
            return False

    async def stop_sound_device(self, hass, device_id: str, device_type: int = 1) -> bool:
        await self.refresh_token_if_needed(hass)
        try:
            payload = build_execute_action_request(
                device_type=device_type,
                device_canonic_id=device_id,
                action="stop_sound",
                gcm_token=self.gcm_token,
            )
            await self._nova_request(NOVA_EXECUTE_ACTION, payload)
            return True
        except Exception as err:
            _LOGGER.error("Failed to stop sound on %s: %s", device_id, err)
            return False

    async def locate_device(self, hass, device_id: str, device_type: int = 1) -> bool:
        await self.refresh_token_if_needed(hass)
        try:
            payload = build_execute_action_request(
                device_type=device_type,
                device_canonic_id=device_id,
                action="locate",
                gcm_token=self.gcm_token,
            )
            await self._nova_request(NOVA_EXECUTE_ACTION, payload)
            return True
        except Exception as err:
            _LOGGER.error("Failed to locate device %s: %s", device_id, err)
            return False

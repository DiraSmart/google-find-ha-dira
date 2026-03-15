"""Google Find My Device API client.

Handles authentication (GCM checkin + gpsoauth) and Nova API calls
for listing devices, ringing, and locating.
"""

import binascii
import logging
import time

import aiohttp

from .const import (
    ADM_CERT_SHA1,
    ADM_PACKAGE,
    ADM_SENDER_ID,
    ADM_SERVICE,
    GCM_CHECKIN_URL,
    GCM_REGISTER_URL,
    GMS_CERT_SHA1,
    GMS_PACKAGE,
    NOVA_EXECUTE_ACTION,
    NOVA_HEADERS_BASE,
    NOVA_LIST_DEVICES,
)
from .proto import (
    build_checkin_request,
    build_execute_action_request,
    build_list_devices_request,
    decode_protobuf,
    decode_recursive,
    get_field,
    get_field_list,
)

_LOGGER = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication fails."""


class APIError(Exception):
    """Raised when an API call fails."""


class GoogleFindDeviceAPI:
    """Client for Google Find My Device using Nova API."""

    def __init__(self, email: str, app_password: str):
        self.email = email
        self.app_password = app_password
        self.android_id: int | None = None
        self.security_token: int | None = None
        self.gcm_token: str | None = None
        self.master_token: str | None = None
        self.adm_token: str | None = None
        self.token_expiry: float = 0
        self.devices: dict = {}

    async def authenticate(self, hass) -> bool:
        """Full authentication flow.

        1. GCM checkin -> android_id + security_token
        2. GCM register -> gcm_token (for receiving push responses)
        3. gpsoauth master login -> master_token
        4. gpsoauth oauth -> ADM bearer token
        """
        _LOGGER.debug("Starting authentication flow for %s", self.email)

        # Step 1: GCM Checkin
        await self._gcm_checkin()
        _LOGGER.debug("GCM checkin successful, android_id=%s", self.android_id)

        # Step 2: GCM Register (optional - needed for ring/locate responses)
        try:
            await self._gcm_register()
            _LOGGER.debug("GCM registration successful")
        except Exception as err:
            _LOGGER.warning(
                "GCM registration failed (ring may still work): %s", err
            )
            self.gcm_token = ""

        # Step 3 & 4: gpsoauth
        await self._get_adm_token(hass)
        _LOGGER.info("Authentication successful for %s", self.email)
        return True

    async def _gcm_checkin(self):
        """Perform GCM checkin to get android_id and security_token.

        This uses the OLD GCM protocol (not Firebase Installations),
        which is more stable and not blocked by Google.
        """
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

        # Parse the checkin response protobuf
        fields = decode_protobuf(response_data)

        # android_id is in field 7 (can be varint or fixed64)
        android_id_values = fields.get(7, [])
        if not android_id_values:
            raise AuthenticationError(
                "GCM checkin response missing android_id (field 7)"
            )
        self.android_id = android_id_values[0]

        # security_token is in field 11
        security_token_values = fields.get(11, [])
        if not security_token_values:
            raise AuthenticationError(
                "GCM checkin response missing security_token (field 11)"
            )
        self.security_token = security_token_values[0]

    async def _gcm_register(self):
        """Register with GCM to get a registration token for push notifications."""
        if not self.android_id or not self.security_token:
            raise AuthenticationError("Must call _gcm_checkin first")

        data = {
            "app": ADM_PACKAGE,
            "X-subtype": ADM_SENDER_ID,
            "device": str(self.android_id),
            "sender": ADM_SENDER_ID,
            "X-scope": "GCM",
            "X-gmsv": "243530062",
            "X-osmv": "28",
            "X-app_ver": "20006320",
            "X-app_ver_name": "0.63.20",
            "cert": ADM_CERT_SHA1,
        }

        headers = {
            "Authorization": f"AidLogin {self.android_id}:{self.security_token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Android-GCM/1.5",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                GCM_REGISTER_URL, data=data, headers=headers
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise AuthenticationError(
                        f"GCM registration failed (HTTP {resp.status}): {text}"
                    )

                response_text = await resp.text()

        if response_text.startswith("token="):
            self.gcm_token = response_text.split("=", 1)[1].strip()
        elif "Error" in response_text:
            raise AuthenticationError(f"GCM registration error: {response_text}")
        else:
            _LOGGER.warning("Unexpected GCM registration response: %s", response_text)
            self.gcm_token = ""

    async def _get_adm_token(self, hass):
        """Get Android Device Manager OAuth token using gpsoauth."""
        try:
            from gpsoauth import perform_master_login, perform_oauth
        except ImportError as err:
            raise AuthenticationError(
                "gpsoauth library not installed. Check manifest.json requirements."
            ) from err

        android_id_hex = format(self.android_id, "x")

        # Step 3: Master login
        master_resp = await hass.async_add_executor_job(
            perform_master_login,
            self.email,
            self.app_password,
            android_id_hex,
        )

        if "Token" not in master_resp:
            error = master_resp.get("Error", "Unknown error")
            _LOGGER.error("Master login failed: %s", master_resp)
            raise AuthenticationError(f"Google login failed: {error}")

        self.master_token = master_resp["Token"]
        _LOGGER.debug("Master login successful")

        # Step 4: Get ADM service token
        oauth_resp = await hass.async_add_executor_job(
            perform_oauth,
            self.email,
            self.master_token,
            android_id_hex,
            ADM_SERVICE,
            ADM_PACKAGE,
            ADM_CERT_SHA1,
        )

        if "Auth" not in oauth_resp:
            error = oauth_resp.get("Error", "Unknown error")
            _LOGGER.error("OAuth failed: %s", oauth_resp)
            raise AuthenticationError(f"Failed to get ADM token: {error}")

        self.adm_token = oauth_resp["Auth"]
        self.token_expiry = time.time() + 3500  # Tokens last ~1 hour

    async def refresh_token_if_needed(self, hass):
        """Refresh the ADM token if it's expired or about to expire."""
        if time.time() > self.token_expiry:
            _LOGGER.debug("ADM token expired, refreshing...")
            await self._get_adm_token(hass)

    def _nova_headers(self):
        """Get headers for Nova API requests."""
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
            # Response might be binary, not hex
            return await resp.read()

    async def list_devices(self, hass) -> dict:
        """List all devices via Nova API.

        Returns a dict of {device_id: device_info}.
        Requests both Android devices and Spot devices.
        """
        await self.refresh_token_if_needed(hass)

        all_devices = {}

        for device_type, type_name in [(1, "Android"), (2, "Spot")]:
            try:
                payload = build_list_devices_request(device_type)
                response_data = await self._nova_request(NOVA_LIST_DEVICES, payload)

                if not response_data:
                    _LOGGER.debug("No response for %s devices", type_name)
                    continue

                devices = self._parse_device_list(response_data, device_type)
                all_devices.update(devices)
                _LOGGER.debug(
                    "Found %d %s device(s)", len(devices), type_name
                )

            except APIError as err:
                _LOGGER.warning("Error listing %s devices: %s", type_name, err)
            except Exception as err:
                _LOGGER.warning(
                    "Unexpected error listing %s devices: %s", type_name, err
                )

        self.devices = all_devices
        return all_devices

    def _parse_device_list(self, data: bytes, device_type: int) -> dict:
        """Parse a DevicesList protobuf response."""
        decoded = decode_recursive(data, max_depth=8)
        devices = {}

        if not isinstance(decoded, dict):
            _LOGGER.warning("Failed to decode device list response")
            return devices

        # DevicesList has repeated DeviceMetadata in field 2
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
        """Parse a single DeviceMetadata protobuf entry."""
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

        # Try to extract device name (commonly field 2 for userDefinedDeviceName)
        name = self._find_string_field(entry, "name")
        if name:
            device_info["name"] = name

        # Try to extract canonical ID (commonly in identifierInformation)
        device_id = self._find_device_id(entry)
        if device_id:
            device_info["id"] = device_id

        # Try to extract location data
        location = self._find_location(entry)
        if location:
            device_info.update(location)

        # Try to extract model info
        model = self._find_string_field(entry, "model")
        if model:
            device_info["model"] = model

        # Log the raw structure for debugging if we couldn't parse essential fields
        if not device_info["id"]:
            _LOGGER.debug("Could not extract device ID from entry: %s", entry)

        return device_info

    def _find_string_field(self, data: dict, hint: str) -> str | None:
        """Search for a string field in the protobuf data."""
        for field_num, value in data.items():
            if isinstance(value, str) and len(value) > 1:
                return value
            if isinstance(value, list):
                for v in value:
                    if isinstance(v, str) and len(v) > 1:
                        return v
        return None

    def _find_device_id(self, data: dict) -> str | None:
        """Extract the canonical device ID from a DeviceMetadata entry."""
        # The ID is typically in identifierInformation -> canonicIds -> canonicId -> id
        # We search recursively for a field that looks like a canonical ID

        def _search(d, depth=0):
            if depth > 6 or not isinstance(d, dict):
                return None
            for field_num, value in d.items():
                if isinstance(value, str):
                    # Canonical IDs are typically long alphanumeric strings
                    if len(value) > 10 and not value.startswith("http"):
                        return value
                elif isinstance(value, dict):
                    result = _search(value, depth + 1)
                    if result:
                        return result
                elif isinstance(value, list):
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
        """Extract location data from device metadata.

        Looks for latitude/longitude in various protobuf structures.
        Handles both encrypted and potentially unencrypted locations.
        """
        # Location data might be in various nested fields
        # For unencrypted locations, look for sfixed32 pairs (lat/lon as int * 1e7)
        # For now, try to find any numeric values that look like coordinates

        def _search_location(d, depth=0):
            if depth > 8 or not isinstance(d, dict):
                return None

            # Check if this dict has fields 1 and 2 with coordinate-like values
            f1 = d.get(1)
            f2 = d.get(2)
            f3 = d.get(3)

            if isinstance(f1, (int, float)) and isinstance(f2, (int, float)):
                lat = f1
                lon = f2

                # Check if these are raw coordinates (e.g., from sfixed32 * 1e7)
                if abs(lat) > 1000000:  # Likely in 1e7 format
                    lat = lat / 1e7
                    lon = lon / 1e7

                # Validate coordinate ranges
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    result = {"latitude": lat, "longitude": lon}
                    if isinstance(f3, (int, float)):
                        result["accuracy"] = f3
                    return result

            # Recurse into sub-messages
            for field_num, value in d.items():
                if isinstance(value, dict):
                    result = _search_location(value, depth + 1)
                    if result:
                        return result
                elif isinstance(value, list):
                    for v in value:
                        if isinstance(v, dict):
                            result = _search_location(v, depth + 1)
                            if result:
                                return result

            return None

        return _search_location(data)

    async def ring_device(self, hass, device_id: str, device_type: int = 1) -> bool:
        """Send a ring command to a device."""
        await self.refresh_token_if_needed(hass)

        try:
            payload = build_execute_action_request(
                device_type=device_type,
                device_canonic_id=device_id,
                action="ring",
                gcm_token=self.gcm_token or "",
            )
            await self._nova_request(NOVA_EXECUTE_ACTION, payload)
            _LOGGER.info("Ring command sent to device %s", device_id)
            return True
        except Exception as err:
            _LOGGER.error("Failed to ring device %s: %s", device_id, err)
            return False

    async def stop_sound_device(self, hass, device_id: str, device_type: int = 1) -> bool:
        """Send a stop sound command to a device."""
        await self.refresh_token_if_needed(hass)

        try:
            payload = build_execute_action_request(
                device_type=device_type,
                device_canonic_id=device_id,
                action="stop_sound",
                gcm_token=self.gcm_token or "",
            )
            await self._nova_request(NOVA_EXECUTE_ACTION, payload)
            _LOGGER.info("Stop sound command sent to device %s", device_id)
            return True
        except Exception as err:
            _LOGGER.error("Failed to stop sound on device %s: %s", device_id, err)
            return False

    async def locate_device(self, hass, device_id: str, device_type: int = 1) -> bool:
        """Send a locate command to request fresh location data."""
        await self.refresh_token_if_needed(hass)

        try:
            payload = build_execute_action_request(
                device_type=device_type,
                device_canonic_id=device_id,
                action="locate",
                gcm_token=self.gcm_token or "",
            )
            await self._nova_request(NOVA_EXECUTE_ACTION, payload)
            _LOGGER.info("Locate command sent to device %s", device_id)
            return True
        except Exception as err:
            _LOGGER.error("Failed to locate device %s: %s", device_id, err)
            return False

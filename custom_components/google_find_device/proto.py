"""Simple protobuf encoder/decoder for Google Find My Device API.

Implements manual protobuf encoding/decoding for the specific messages
needed by the Nova API, avoiding the need for compiled .proto files.
"""

import struct
import uuid


# --- Varint encoding/decoding ---

def encode_varint(value):
    """Encode an integer as a protobuf varint."""
    if value < 0:
        value = value & 0xFFFFFFFFFFFFFFFF  # Convert to unsigned 64-bit
    result = []
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def decode_varint(data, offset):
    """Decode a varint from data at offset. Returns (value, new_offset)."""
    result = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise ValueError("Unexpected end of data while decoding varint")
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            break
        shift += 7
    return result, offset


# --- Field encoding ---

def encode_tag(field_number, wire_type):
    """Encode a protobuf field tag."""
    return encode_varint((field_number << 3) | wire_type)


def encode_varint_field(field_number, value):
    """Encode a varint field (wire type 0)."""
    return encode_tag(field_number, 0) + encode_varint(value)


def encode_bytes_field(field_number, data):
    """Encode a length-delimited field (wire type 2) - bytes, string, or embedded message."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return encode_tag(field_number, 2) + encode_varint(len(data)) + data


def encode_fixed64_field(field_number, value):
    """Encode a fixed64 field (wire type 1)."""
    return encode_tag(field_number, 1) + struct.pack("<Q", value)


def encode_fixed32_field(field_number, value):
    """Encode a fixed32 field (wire type 5)."""
    return encode_tag(field_number, 5) + struct.pack("<I", value)


def encode_sfixed32_field(field_number, value):
    """Encode a sfixed32 field (wire type 5)."""
    return encode_tag(field_number, 5) + struct.pack("<i", value)


# --- Generic protobuf decoder ---

def decode_protobuf(data):
    """Decode a protobuf message into a dict of {field_number: [values]}.

    Length-delimited fields are stored as raw bytes. Use try_decode_message()
    to attempt recursive decoding of embedded messages.
    """
    if not isinstance(data, (bytes, bytearray)):
        return {}

    fields = {}
    offset = 0

    while offset < len(data):
        try:
            tag, offset = decode_varint(data, offset)
        except ValueError:
            break

        field_number = tag >> 3
        wire_type = tag & 0x07

        if wire_type == 0:  # Varint
            value, offset = decode_varint(data, offset)
        elif wire_type == 1:  # 64-bit
            if offset + 8 > len(data):
                break
            value = struct.unpack("<Q", data[offset : offset + 8])[0]
            offset += 8
        elif wire_type == 2:  # Length-delimited
            length, offset = decode_varint(data, offset)
            if offset + length > len(data):
                break
            value = data[offset : offset + length]
            offset += length
        elif wire_type == 5:  # 32-bit
            if offset + 4 > len(data):
                break
            value = struct.unpack("<I", data[offset : offset + 4])[0]
            offset += 4
        else:
            break  # Unknown wire type

        if field_number not in fields:
            fields[field_number] = []
        fields[field_number].append(value)

    return fields


def decode_recursive(data, max_depth=10):
    """Recursively decode protobuf, attempting to parse embedded messages."""
    if max_depth <= 0 or not isinstance(data, (bytes, bytearray)):
        return data

    fields = decode_protobuf(data)
    if not fields:
        return data

    result = {}
    for field_num, values in fields.items():
        decoded_values = []
        for v in values:
            if isinstance(v, (bytes, bytearray)):
                # Try to decode as embedded message
                try:
                    sub = decode_recursive(v, max_depth - 1)
                    if isinstance(sub, dict) and sub:
                        decoded_values.append(sub)
                    else:
                        # Try as UTF-8 string
                        try:
                            decoded_values.append(v.decode("utf-8"))
                        except (UnicodeDecodeError, ValueError):
                            decoded_values.append(v)
                except Exception:
                    decoded_values.append(v)
            else:
                decoded_values.append(v)

        result[field_num] = decoded_values if len(decoded_values) > 1 else decoded_values[0]

    return result


def get_field(decoded, *path):
    """Navigate a decoded protobuf structure by field numbers.

    Example: get_field(data, 2, 1, 3) gets field 2 -> field 1 -> field 3.
    If a field contains a list, gets the first element.
    """
    current = decoded
    for field_num in path:
        if isinstance(current, dict):
            val = current.get(field_num)
            if val is None:
                return None
            if isinstance(val, list):
                current = val[0] if val else None
            else:
                current = val
        else:
            return None
    return current


def get_field_list(decoded, *path):
    """Like get_field but returns a list for the final field (for repeated fields)."""
    if len(path) == 0:
        return []

    current = decoded
    for field_num in path[:-1]:
        if isinstance(current, dict):
            val = current.get(field_num)
            if val is None:
                return []
            if isinstance(val, list):
                current = val[0] if val else None
            else:
                current = val
        else:
            return []

    last_field = path[-1]
    if isinstance(current, dict):
        val = current.get(last_field)
        if val is None:
            return []
        if isinstance(val, list):
            return val
        return [val]
    return []


# --- Specific message builders for Nova API ---

def build_checkin_request():
    """Build a GCM checkin request protobuf.

    AndroidCheckinRequest {
      id: 0 (field 1)
      checkin: AndroidCheckinProto (field 4) {
        build: AndroidBuildProto (field 1) {
          sdkVersion: 28 (field 3)
        }
        lastCheckinMs: 0 (field 2)
      }
      version: 3 (field 14)
    }
    """
    # Pre-computed bytes for the minimal checkin request
    build_proto = encode_varint_field(3, 28)  # sdkVersion = 28
    checkin_proto = encode_bytes_field(1, build_proto) + encode_varint_field(2, 0)
    request = (
        encode_varint_field(1, 0)  # id = 0 (new registration)
        + encode_bytes_field(4, checkin_proto)  # checkin
        + encode_varint_field(14, 3)  # version = 3
    )
    return request


def build_list_devices_request(device_type=1):
    """Build a Nova API nbe_list_devices request.

    DevicesListRequest {
      deviceListRequestPayload: DevicesListRequestPayload (field 1) {
        type: DeviceType (field 1) - 1=ANDROID, 2=SPOT
        id: string UUID (field 3)
      }
    }

    Args:
        device_type: 1 for ANDROID_DEVICE, 2 for SPOT_DEVICE
    """
    request_id = str(uuid.uuid4())
    payload = encode_varint_field(1, device_type) + encode_bytes_field(3, request_id)
    request = encode_bytes_field(1, payload)
    return request


def build_execute_action_request(
    device_type,
    device_canonic_id,
    action,
    gcm_token="",
    request_uuid=None,
    fmd_client_uuid=None,
    component=0,
):
    """Build a Nova API nbe_execute_action request.

    Args:
        device_type: 1 for ANDROID, 2 for SPOT
        device_canonic_id: The device's canonical ID
        action: "ring", "stop_sound", or "locate"
        gcm_token: GCM registration token (for receiving responses)
        request_uuid: Unique request ID (auto-generated if None)
        fmd_client_uuid: Client UUID (auto-generated if None)
        component: Device component (0=unspecified, 1=right, 2=left, 3=case)
    """
    if request_uuid is None:
        request_uuid = str(uuid.uuid4())
    if fmd_client_uuid is None:
        fmd_client_uuid = str(uuid.uuid4())

    # ExecuteActionScope (field 1)
    scope_device = encode_bytes_field(1, encode_bytes_field(1, device_canonic_id))
    scope = encode_varint_field(1, device_type) + encode_bytes_field(2, scope_device)

    # ExecuteActionType (field 2)
    if action == "ring":
        action_inner = encode_varint_field(1, component)  # DeviceComponent
        action_type = encode_bytes_field(31, action_inner)  # startSound
    elif action == "stop_sound":
        action_inner = encode_varint_field(1, component)
        action_type = encode_bytes_field(32, action_inner)  # stopSound
    elif action == "locate":
        import time
        locate_inner = (
            encode_bytes_field(2, encode_varint_field(1, int(time.time())))
            + encode_varint_field(3, 4)  # FMDN_ALL_LOCATIONS
        )
        action_type = encode_bytes_field(30, locate_inner)  # locateTracker
    else:
        raise ValueError(f"Unknown action: {action}")

    # ExecuteActionRequestMetadata (field 3)
    metadata = (
        encode_varint_field(1, device_type)
        + encode_bytes_field(2, request_uuid)
        + encode_bytes_field(3, fmd_client_uuid)
    )
    if gcm_token:
        metadata += encode_bytes_field(4, encode_bytes_field(1, gcm_token))
    metadata += encode_varint_field(6, 1)  # unknown = true

    # Full request
    request = (
        encode_bytes_field(1, scope)
        + encode_bytes_field(2, action_type)
        + encode_bytes_field(3, metadata)
    )
    return request

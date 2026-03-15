#!/usr/bin/env python3
"""
Google Find My Device - Master Token Helper
============================================
Run this script on your PC to obtain a master token
for the Home Assistant integration.

Requirements:
    pip install cryptography aiohttp

Usage:
    python get_token.py
"""

import asyncio
import base64
import hashlib
import struct
import sys
import webbrowser

try:
    import aiohttp
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
except ImportError:
    print("Missing dependencies. Install them with:")
    print("  pip install cryptography aiohttp")
    sys.exit(1)


AUTH_URL = "https://android.clients.google.com/auth"
CHECKIN_URL = "https://android.clients.google.com/checkin"
EMBEDDED_SETUP_URL = "https://accounts.google.com/EmbeddedSetup"


def encode_varint(value):
    result = []
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def decode_protobuf(data):
    fields = {}
    offset = 0
    while offset < len(data):
        tag = 0
        shift = 0
        while True:
            if offset >= len(data):
                return fields
            byte = data[offset]
            offset += 1
            tag |= (byte & 0x7F) << shift
            if not (byte & 0x80):
                break
            shift += 7
        field_number = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 0:
            value = 0
            shift = 0
            while True:
                if offset >= len(data):
                    return fields
                byte = data[offset]
                offset += 1
                value |= (byte & 0x7F) << shift
                if not (byte & 0x80):
                    break
                shift += 7
        elif wire_type == 1:
            if offset + 8 > len(data):
                return fields
            value = struct.unpack("<Q", data[offset:offset + 8])[0]
            offset += 8
        elif wire_type == 2:
            length = 0
            shift = 0
            while True:
                if offset >= len(data):
                    return fields
                byte = data[offset]
                offset += 1
                length |= (byte & 0x7F) << shift
                if not (byte & 0x80):
                    break
                shift += 7
            if offset + length > len(data):
                return fields
            value = data[offset:offset + length]
            offset += length
        elif wire_type == 5:
            if offset + 4 > len(data):
                return fields
            value = struct.unpack("<I", data[offset:offset + 4])[0]
            offset += 4
        else:
            return fields
        if field_number not in fields:
            fields[field_number] = []
        fields[field_number].append(value)
    return fields


def parse_response(text: str) -> dict:
    result = {}
    for line in text.strip().split("\n"):
        if "=" in line:
            k, v = line.split("=", 1)
            result[k] = v
    return result


async def gcm_checkin() -> int:
    """GCM checkin to get android_id."""
    def tag(f, w):
        return encode_varint((f << 3) | w)

    build = tag(3, 0) + encode_varint(28)
    checkin = tag(1, 2) + encode_varint(len(build)) + build + tag(2, 0) + encode_varint(0)
    request = (
        tag(1, 0) + encode_varint(0)
        + tag(4, 2) + encode_varint(len(checkin)) + checkin
        + tag(14, 0) + encode_varint(3)
    )

    async with aiohttp.ClientSession() as session:
        async with session.post(
            CHECKIN_URL,
            data=request,
            headers={"Content-Type": "application/x-protobuf"},
        ) as resp:
            if resp.status != 200:
                raise Exception(f"GCM checkin failed: HTTP {resp.status}")
            data = await resp.read()

    fields = decode_protobuf(data)
    android_id_list = fields.get(7, [])
    if not android_id_list:
        raise Exception("No android_id in checkin response")
    return android_id_list[0]


async def exchange_oauth_token(email: str, oauth_token: str, android_id: str) -> dict:
    """Exchange a browser OAuth token for a master token."""
    data = {
        "accountType": "HOSTED_OR_GOOGLE",
        "Email": email,
        "has_permission": "1",
        "add_account": "1",
        "Token": oauth_token,
        "service": "ac2dm",
        "source": "android",
        "androidId": android_id,
        "device_country": "us",
        "operatorCountry": "us",
        "lang": "en",
        "sdk_version": "28",
        "callerPkg": "com.google.android.gms",
        "callerSig": "38918a453d07199354f8b19af05ec6562ced5788",
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "GoogleAuth/1.4 (Nexus 5X PQ3B.190801.002)",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(AUTH_URL, data=data, headers=headers) as resp:
            text = await resp.text()

    return parse_response(text)


async def test_adm_token(email: str, master_token: str, android_id: str) -> bool:
    """Test if we can get an ADM token from the master token."""
    data = {
        "accountType": "HOSTED_OR_GOOGLE",
        "Email": email,
        "has_permission": "1",
        "EncryptedPasswd": master_token,
        "service": "oauth2:https://www.googleapis.com/auth/android_device_manager",
        "source": "android",
        "androidId": android_id,
        "app": "com.google.android.apps.adm",
        "client_sig": "38918a453d07199354f8b19af05ec6562ced5788",
        "device_country": "us",
        "operatorCountry": "us",
        "lang": "en",
        "sdk_version": "28",
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "GoogleAuth/1.4 (Nexus 5X PQ3B.190801.002)",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(AUTH_URL, data=data, headers=headers) as resp:
            text = await resp.text()

    result = parse_response(text)
    return "Auth" in result


async def main():
    print("=" * 60)
    print("  Google Find My Device - Master Token Helper")
    print("=" * 60)
    print()
    print("This script will help you get a master token")
    print("by signing in through your browser.")
    print()

    email = input("Step 1 - Enter your Google Email: ").strip()

    print()
    print("[1/4] Performing GCM checkin...")
    try:
        android_id = await gcm_checkin()
        android_id_hex = format(android_id, "x")
        print(f"  OK - android_id: {android_id_hex}")
    except Exception as e:
        print(f"  FAILED: {e}")
        return

    print()
    print("[2/4] Opening browser for Google sign-in...")
    print()
    print("  A browser window will open to Google's sign-in page.")
    print("  1. Sign in with your Google account")
    print("  2. After signing in, you'll see a page that says")
    print('     "One moment please..." or similar')
    print("  3. Press F12 to open Developer Tools")
    print("  4. Go to: Application > Cookies > accounts.google.com")
    print('  5. Find the cookie named "oauth_token"')
    print("  6. Copy its VALUE (right-click > Copy value)")
    print()

    input("Press Enter to open the browser...")
    webbrowser.open(EMBEDDED_SETUP_URL)

    print()
    oauth_token = input("Step 2 - Paste the oauth_token cookie value here: ").strip()

    if not oauth_token:
        print("No token provided. Exiting.")
        return

    print()
    print("[3/4] Exchanging token for master token...")
    result = await exchange_oauth_token(email, oauth_token, android_id_hex)

    if "Token" not in result:
        print(f"  FAILED: {result.get('Error', 'Unknown error')}")
        print(f"  Full response: {result}")
        print()
        print("  Tips:")
        print("  - Make sure you copied the FULL oauth_token value")
        print("  - The token should be a long string (100+ characters)")
        print("  - Try signing in again and getting a fresh token")
        return

    master_token = result["Token"]
    print("  OK - Master token obtained!")

    print()
    print("[4/4] Testing ADM OAuth...")
    works = await test_adm_token(email, master_token, android_id_hex)
    if works:
        print("  OK - ADM token verified! Everything works.")
    else:
        print("  WARNING - ADM exchange failed, but try the token anyway.")

    print()
    print("=" * 60)
    print("  SUCCESS! Copy the token below into Home Assistant:")
    print("=" * 60)
    print()
    print(master_token)
    print()
    print("=" * 60)
    print()
    print("In Home Assistant:")
    print("1. Settings > Devices & Services > Add Integration")
    print("2. Search 'Google Find My Device'")
    print("3. Choose 'Master Token (recommended)'")
    print(f"4. Email: {email}")
    print("5. Paste the master token above")
    print()


if __name__ == "__main__":
    asyncio.run(main())

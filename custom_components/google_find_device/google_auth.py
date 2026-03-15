"""Google authentication without gpsoauth dependency.

Implements the Google auth protocol using only the `cryptography` library
(which Home Assistant already includes). No external dependencies needed.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import struct

import aiohttp
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

_LOGGER = logging.getLogger(__name__)

AUTH_URL = "https://android.clients.google.com/auth"

# Google's public RSA key for password encryption
GOOGLE_PUB_KEY_B64 = (
    "AAAAgMom/1a/v0lblO2Ubrt60J2gcuXSljGFQXgcyZWveWLEwo6prwgi3"
    "iJIZdodyhKZQrNWp5nKJ3srRXcUW+F1BD3baEVGcmEgqaLZUNBjm057pK"
    "RI16kB0YppeGx5qIQ5QjKzsR8ETQbKLNWgRY0QRNVz34kMJR3P/LgHax/"
    "6rmf5AAAAAwEAAQ=="
)


def _parse_google_key():
    """Parse Google's public RSA key from the base64-encoded blob."""
    key_bytes = base64.b64decode(GOOGLE_PUB_KEY_B64)

    i = 0
    mod_len = struct.unpack(">I", key_bytes[i : i + 4])[0]
    i += 4
    modulus = int.from_bytes(key_bytes[i : i + mod_len], byteorder="big")
    i += mod_len
    exp_len = struct.unpack(">I", key_bytes[i : i + 4])[0]
    i += 4
    exponent = int.from_bytes(key_bytes[i : i + exp_len], byteorder="big")

    return key_bytes, modulus, exponent


def _create_signature(email: str, password: str) -> str:
    """Encrypt email+password using Google's public RSA key."""
    key_bytes, modulus, exponent = _parse_google_key()

    sha1_hash = hashlib.sha1(key_bytes).digest()[:4]
    plaintext = (email + "\x00" + password).encode("utf-8")

    public_numbers = RSAPublicNumbers(e=exponent, n=modulus)
    public_key = public_numbers.public_key()

    ciphertext = public_key.encrypt(
        plaintext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA1()),
            algorithm=hashes.SHA1(),
            label=None,
        ),
    )

    result = b"\x00" + sha1_hash + ciphertext
    return base64.urlsafe_b64encode(result).decode("ascii")


def _parse_auth_response(text: str) -> dict:
    """Parse Google's key=value auth response."""
    result = {}
    for line in text.strip().split("\n"):
        if "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


async def perform_master_login(
    email: str,
    password: str,
    android_id: str,
) -> dict:
    """Perform master login to Google services.

    Tries encrypted password first, falls back to plaintext Passwd
    (which works with App Passwords).
    """
    encrypted_passwd = _create_signature(email, password)

    # Strategy 1: EncryptedPasswd (standard gpsoauth approach)
    data = {
        "accountType": "HOSTED_OR_GOOGLE",
        "Email": email,
        "has_permission": "1",
        "add_account": "1",
        "EncryptedPasswd": encrypted_passwd,
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
        "Accept": "*/*",
        "Connection": "keep-alive",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(AUTH_URL, data=data, headers=headers) as resp:
            response_text = await resp.text()

    result = _parse_auth_response(response_text)

    if "Token" in result:
        _LOGGER.debug("Master login succeeded with EncryptedPasswd")
        return result

    _LOGGER.debug(
        "EncryptedPasswd failed (%s), trying plaintext Passwd for App Password...",
        result.get("Error", "unknown"),
    )

    # Strategy 2: Plain Passwd field (works with App Passwords)
    data_plain = {
        "accountType": "HOSTED_OR_GOOGLE",
        "Email": email,
        "has_permission": "1",
        "add_account": "1",
        "Passwd": password,
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

    async with aiohttp.ClientSession() as session:
        async with session.post(AUTH_URL, data=data_plain, headers=headers) as resp:
            response_text2 = await resp.text()

    result2 = _parse_auth_response(response_text2)

    if "Token" in result2:
        _LOGGER.debug("Master login succeeded with plain Passwd")
        return result2

    # Strategy 3: Try without spaces in password
    password_nospaces = password.replace(" ", "")
    if password_nospaces != password:
        data_plain["Passwd"] = password_nospaces

        async with aiohttp.ClientSession() as session:
            async with session.post(AUTH_URL, data=data_plain, headers=headers) as resp:
                response_text3 = await resp.text()

        result3 = _parse_auth_response(response_text3)
        if "Token" in result3:
            _LOGGER.debug("Master login succeeded with password without spaces")
            return result3

    _LOGGER.error(
        "All login strategies failed. Response 1: %s | Response 2: %s",
        response_text[:300],
        response_text2[:300],
    )
    return result2


async def perform_oauth(
    email: str,
    master_token: str,
    android_id: str,
    service: str,
    app: str,
    client_sig: str,
) -> dict:
    """Exchange master token for a service-specific OAuth token."""
    data = {
        "accountType": "HOSTED_OR_GOOGLE",
        "Email": email,
        "has_permission": "1",
        "EncryptedPasswd": master_token,
        "service": service,
        "source": "android",
        "androidId": android_id,
        "app": app,
        "client_sig": client_sig,
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
            response_text = await resp.text()

    result = _parse_auth_response(response_text)
    if "Auth" not in result:
        _LOGGER.error("OAuth response: %s", response_text[:500])
    return result

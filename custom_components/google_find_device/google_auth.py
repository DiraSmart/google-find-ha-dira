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

    # Format: 4-byte big-endian modulus length, modulus bytes,
    #         4-byte big-endian exponent length, exponent bytes
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
    """Encrypt email+password using Google's public RSA key.

    This replicates gpsoauth's signature creation using only
    the `cryptography` library.
    """
    key_bytes, modulus, exponent = _parse_google_key()

    # SHA1 hash of the key (first 4 bytes used as key identifier)
    sha1_hash = hashlib.sha1(key_bytes).digest()[:4]

    # Plaintext: email + null byte + password
    plaintext = (email + "\x00" + password).encode("utf-8")

    # Build RSA public key and encrypt with OAEP
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

    # Result format: 0x00 + 4-byte key hash + encrypted data
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

    Returns dict with 'Token' key on success, or 'Error' on failure.
    """
    encrypted_passwd = _create_signature(email, password)

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
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(AUTH_URL, data=data) as resp:
            response_text = await resp.text()

    result = _parse_auth_response(response_text)
    if "Token" not in result and "Auth" not in result:
        _LOGGER.error("Master login response: %s", response_text[:500])
    return result


async def perform_oauth(
    email: str,
    master_token: str,
    android_id: str,
    service: str,
    app: str,
    client_sig: str,
) -> dict:
    """Exchange master token for a service-specific OAuth token.

    Returns dict with 'Auth' key on success, or 'Error' on failure.
    """
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

    async with aiohttp.ClientSession() as session:
        async with session.post(AUTH_URL, data=data) as resp:
            response_text = await resp.text()

    result = _parse_auth_response(response_text)
    if "Auth" not in result:
        _LOGGER.error("OAuth response: %s", response_text[:500])
    return result

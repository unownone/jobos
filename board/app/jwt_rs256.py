"""Local RS256 checks. No key fetch and no token text in errors."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

# DER DigestInfo prefix for SHA-256, from RFC 8017.
_SHA256_DIGESTINFO = bytes.fromhex("3031300d060960864801650304020105000420")


class JwtError(ValueError):
    """The token failed a local check. Messages stay generic."""


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode(segment + padding)
    except Exception as exc:
        raise JwtError("invalid token encoding") from exc


def _read_length(data: bytes, index: int) -> tuple[int, int]:
    if index >= len(data):
        raise JwtError("access public key is invalid")
    first = data[index]
    index += 1
    if first < 0x80:
        return first, index
    count = first & 0x7F
    if count == 0 or count > 4 or index + count > len(data):
        raise JwtError("access public key is invalid")
    length = int.from_bytes(data[index : index + count], "big")
    return length, index + count


def _expect(data: bytes, index: int, tag: int) -> int:
    if index >= len(data) or data[index] != tag:
        raise JwtError("access public key is invalid")
    return index + 1


def _read_integer(data: bytes, index: int) -> tuple[int, int]:
    index = _expect(data, index, 0x02)
    length, index = _read_length(data, index)
    if length < 1 or index + length > len(data):
        raise JwtError("access public key is invalid")
    return int.from_bytes(data[index : index + length], "big"), index + length


def load_rsa_public_pem(pem: str) -> tuple[int, int]:
    """Return modulus and exponent from an SPKI PEM (BEGIN PUBLIC KEY)."""
    body = "".join(
        line.strip() for line in pem.splitlines() if line.strip() and not line.startswith("-----")
    )
    if not body:
        raise JwtError("access public key is missing")
    try:
        der = base64.b64decode(body, validate=True)
    except Exception as exc:
        raise JwtError("access public key is invalid") from exc
    index = _expect(der, 0, 0x30)
    seq_len, index = _read_length(der, index)
    if index + seq_len != len(der):
        raise JwtError("access public key is invalid")
    index = _expect(der, index, 0x30)
    algo_len, index = _read_length(der, index)
    index += algo_len
    index = _expect(der, index, 0x03)
    bit_len, index = _read_length(der, index)
    if bit_len < 2 or index + bit_len > len(der) or der[index] != 0:
        raise JwtError("access public key is invalid")
    index += 1
    key_end = index + bit_len - 1
    index = _expect(der, index, 0x30)
    rsa_len, index = _read_length(der, index)
    rsa_end = index + rsa_len
    modulus, index = _read_integer(der, index)
    exponent, index = _read_integer(der, index)
    if index != rsa_end or index != key_end or modulus <= 0 or exponent <= 0:
        raise JwtError("access public key is invalid")
    return modulus, exponent


def _rs256_signature_ok(
    signing_input: bytes, signature: bytes, modulus: int, exponent: int
) -> bool:
    digest = hashlib.sha256(signing_input).digest()
    encoded = _SHA256_DIGESTINFO + digest
    key_bytes = (modulus.bit_length() + 7) // 8
    if len(signature) != key_bytes or key_bytes < len(encoded) + 11:
        return False
    value = int.from_bytes(signature, "big")
    if value <= 0 or value >= modulus:
        return False
    em = pow(value, exponent, modulus).to_bytes(key_bytes, "big")
    expected = b"\x00\x01" + (b"\xff" * (key_bytes - len(encoded) - 3)) + b"\x00" + encoded
    return hmac.compare_digest(em, expected)


def decode_rs256(token: str, public_pem: str) -> dict[str, Any]:
    """Verify an RS256 compact JWT and return its claims. Does not check iss, aud, or exp."""
    parts = token.split(".")
    if len(parts) != 3 or not parts[0] or not parts[1] or not parts[2]:
        raise JwtError("invalid token")
    try:
        header = json.loads(_b64url_decode(parts[0]))
        payload = json.loads(_b64url_decode(parts[1]))
        signature = _b64url_decode(parts[2])
    except JwtError:
        raise
    except Exception as exc:
        raise JwtError("invalid token") from exc
    if not isinstance(header, dict) or header.get("alg") != "RS256":
        raise JwtError("unsupported token algorithm")
    if not isinstance(payload, dict):
        raise JwtError("invalid token")
    if not public_pem.strip():
        raise JwtError("access public key is not configured")
    modulus, exponent = load_rsa_public_pem(public_pem)
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    if not _rs256_signature_ok(signing_input, signature, modulus, exponent):
        raise JwtError("invalid token signature")
    return payload

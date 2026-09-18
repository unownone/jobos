"""Password KDF Module. Argon2 stays behind this Interface so stores never see plaintext."""

from __future__ import annotations

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

PASSWORD_MIN_LEN = 8
_HASHER = PasswordHasher()


def new_id(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(16).replace("-", "").replace("_", "")[:22]


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    if not password_hash or password_hash.startswith("!"):
        return False
    try:
        return _HASHER.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False

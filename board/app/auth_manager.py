"""Auth manager stub. Resolution is filled in after the tests fail."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.settings import Settings


class AuthConflict(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=401, detail="conflicting credentials")


class AuthManager:
    def __init__(self, methods: list[Any], *, settings: Settings, db: Any) -> None:
        self.methods = methods
        self.settings = settings
        self.db = db

    @classmethod
    def from_settings(cls, settings: Settings, db: Any) -> AuthManager:
        return cls([], settings=settings, db=db)

    def resolve(self, request: Any) -> None:
        del request
        return None


def install_secret_log_filter() -> None:
    return None

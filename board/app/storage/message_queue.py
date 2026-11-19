"""Message queue port. This slice ships the in-memory test double only.

``send`` takes a dict body. The size limit is the UTF-8 length of compact JSON
(``separators=(",", ":")``, ``ensure_ascii=False``). Anything larger than 128 KiB
is refused. There is no Cloudflare adapter here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

MAX_BODY_BYTES = 128 * 1024


class PayloadTooLarge(ValueError):
    """The JSON encoding of the body is larger than 128 KiB."""

    def __init__(self, size: int) -> None:
        super().__init__(f"message body is {size} bytes; limit is {MAX_BODY_BYTES}")
        self.size = size


@dataclass(frozen=True)
class SentMessage:
    topic: str
    body: dict[str, Any]
    key: str | None


class MessageQueue(Protocol):
    def send(self, topic: str, body: dict[str, Any], key: str | None = None) -> None:
        """Publish one JSON object."""


def _encode(body: dict[str, Any]) -> bytes:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class InlineQueue:
    """Records messages in memory. Tests read ``messages``."""

    def __init__(self) -> None:
        self.messages: list[SentMessage] = []

    def send(self, topic: str, body: dict[str, Any], key: str | None = None) -> None:
        if not isinstance(body, dict):
            raise TypeError("message body must be a dict")
        encoded = _encode(body)
        if len(encoded) > MAX_BODY_BYTES:
            raise PayloadTooLarge(len(encoded))
        self.messages.append(SentMessage(topic=topic, body=dict(body), key=key))

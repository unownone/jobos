"""Public origin for invite / signup / onboarding URLs.

Accepts a full URL, a hostname, or an IP:port combo such as 12.234.244.34:343.
Never put tokens in the origin.
"""

from __future__ import annotations

import re

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def normalize_public_url(raw: str) -> str:
    """Turn host / host:port / URL into an origin with no trailing slash."""
    text = (raw or "").strip().strip('"').strip("'")
    if not text:
        return ""
    text = text.rstrip("/")
    if _SCHEME_RE.match(text):
        return text
    scheme = "https" if _uses_tls_port(text) else "http"
    return f"{scheme}://{text}"


def _uses_tls_port(hostport: str) -> bool:
    if hostport.startswith("["):
        return hostport.endswith("]:443")
    if ":" not in hostport:
        return False
    return hostport.rsplit(":", 1)[-1] == "443"


def resolve_public_url(
    *,
    public_url: str = "",
    public_host: str = "",
    listen_host: str = "",
    listen_port: int = 8787,
) -> str:
    """HUB_PUBLIC_URL wins, then HUB_PUBLIC_HOST, then the listen bind."""
    if (public_url or "").strip():
        return normalize_public_url(public_url)
    if (public_host or "").strip():
        return normalize_public_url(public_host)
    host = (listen_host or "").strip() or "127.0.0.1"
    if host in {"0.0.0.0", "::", "[::]"}:
        host = "127.0.0.1"
    return f"http://{host}:{int(listen_port)}"

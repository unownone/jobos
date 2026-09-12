"""Public URL / host:port normalization for invite origins."""

from __future__ import annotations

from pathlib import Path

from app.urls import normalize_public_url, resolve_public_url


def test_normalize_full_urls() -> None:
    assert normalize_public_url("https://hub.example.test/") == "https://hub.example.test"
    assert normalize_public_url("http://127.0.0.1:8787") == "http://127.0.0.1:8787"


def test_normalize_ip_port_combo() -> None:
    assert normalize_public_url("12.234.244.34:343") == "http://12.234.244.34:343"
    assert normalize_public_url("12.234.244.34") == "http://12.234.244.34"
    assert normalize_public_url("12.234.244.34:443") == "https://12.234.244.34:443"
    assert normalize_public_url("example.com") == "http://example.com"
    assert normalize_public_url("[2001:db8::1]:343") == "http://[2001:db8::1]:343"
    assert normalize_public_url("[2001:db8::1]:443") == "https://[2001:db8::1]:443"


def test_resolve_prefers_url_then_host() -> None:
    assert (
        resolve_public_url(public_url="https://a.example", public_host="1.2.3.4:9")
        == "https://a.example"
    )
    assert resolve_public_url(public_host="12.234.244.34:343") == "http://12.234.244.34:343"
    assert (
        resolve_public_url(listen_host="0.0.0.0", listen_port=8787) == "http://127.0.0.1:8787"
    )


def test_join_url_from_ip_port() -> None:
    from app.identity import join_url
    from app.settings import Settings
    from app.urls import normalize_public_url

    settings = Settings(
        board_dir=Path("."),
        db_path=Path("board.db"),
        host="0.0.0.0",
        port=8787,
        tokens={},
        public_url=normalize_public_url("12.234.244.34:343"),
    )
    assert join_url(settings, "inv1", "s3cret") == "http://12.234.244.34:343/join/inv1?s=s3cret"

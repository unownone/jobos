"""Static Hub UI shell: one theme and one built stylesheet on every page."""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"

PAGES = [
    "landing.html",
    "start.html",
    "index.html",
    "home.html",
    "login.html",
    "signup.html",
    "join.html",
    "onboarding.html",
    "admin.html",
    "data.html",
    "users.html",
    "skills.html",
    "memory.html",
]

APP_CSS = re.compile(r'href="(/static/app/[^"]+\.css)"')


def test_every_html_page_uses_shared_shell() -> None:
    hrefs: list[str] = []
    missing_viewport = []
    missing_theme = []
    missing_css = []
    for name in PAGES:
        text = (STATIC / name).read_text(encoding="utf-8")
        if "viewport-fit=cover" not in text:
            missing_viewport.append(name)
        if "/static/theme.css" not in text:
            missing_theme.append(name)
        match = APP_CSS.search(text)
        if match is None:
            missing_css.append(name)
        else:
            hrefs.append(match.group(1))
    assert not missing_viewport, f"pages missing viewport-fit: {missing_viewport}"
    assert not missing_theme, f"pages missing theme.css: {missing_theme}"
    assert not missing_css, f"pages missing the built stylesheet: {missing_css}"
    assert len(set(hrefs)) == 1, hrefs


def test_hub_css_blocks_are_balanced() -> None:
    text = (STATIC / "hub.css").read_text(encoding="utf-8")
    assert text.count("{") == text.count("}"), "hub.css has an unclosed rule; later layouts nest and drop"
    assert "}\n.drop .menu button" in text.replace("\r\n", "\n")


def test_authenticated_pages_use_the_hub_frame() -> None:
    for name in ("index.html", "home.html", "admin.html", "data.html", "users.html", "skills.html", "memory.html", "onboarding.html"):
        text = (STATIC / name).read_text(encoding="utf-8")
        assert 'data-testid="hub-frame"' in text or "hub-frame" in text, name
        assert "/admin/memory" in text, name


def test_onboarding_keeps_the_profile_fields_and_returns_to_the_board() -> None:
    text = (STATIC / "onboarding.html").read_text(encoding="utf-8")
    assert 'id="full_name"' in text
    assert "/board" in text
    assert 'location.href = "/"' not in text
    assert 'location.href = "/admin"' not in text


def test_board_page_has_rejection_fields() -> None:
    text = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="f_rejection_by"' in text
    assert 'id="f_company_remarks"' in text
    assert 'id="f_user_remarks"' in text
    assert "Rejected by" in text


def test_board_unauthorized_stays_on_hub_login_next() -> None:
    text = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "/login?next=/board" in text
    assert '"/login?next=/"' not in text
    assert "'/login?next=/'" not in text


def test_login_has_the_account_fields() -> None:
    text = (STATIC / "login.html").read_text(encoding="utf-8")
    assert 'id="username"' in text
    assert "Create account" in text

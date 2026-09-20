"""Static Hub UI shell: shared theme + operator CSS on every operator page."""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"

PAGES = [
    "index.html",
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


def test_every_html_page_uses_shared_shell() -> None:
    missing_css = []
    missing_viewport = []
    for name in PAGES:
        text = (STATIC / name).read_text(encoding="utf-8")
        if "/static/hub.css" not in text:
            missing_css.append(name)
        if "/static/theme.css" not in text:
            missing_css.append(f"{name}:theme")
        if "viewport-fit=cover" not in text:
            missing_viewport.append(name)
    assert not missing_css, f"pages missing hub.css: {missing_css}"
    assert not missing_viewport, f"pages missing viewport-fit: {missing_viewport}"


def test_hub_css_blocks_are_balanced() -> None:
    text = (STATIC / "hub.css").read_text(encoding="utf-8")
    assert text.count("{") == text.count("}"), "hub.css has an unclosed rule; later layouts nest and drop"
    assert "}\n.drop .menu button" in text.replace("\r\n", "\n")


def test_authenticated_pages_have_mobile_dock() -> None:
    for name in ("index.html", "admin.html", "data.html", "users.html", "skills.html", "memory.html", "onboarding.html"):
        text = (STATIC / name).read_text(encoding="utf-8")
        assert "hub-dock" in text, name
        assert "hub-rail" in text, name
        assert "/admin/memory" in text, name


def test_onboarding_prefills_saved_profile_and_stays_in_hub() -> None:
    text = (STATIC / "onboarding.html").read_text(encoding="utf-8")
    assert "function fillForm" in text
    assert "function loadProfile" in text
    assert 'Accept: "application/json"' in text
    assert 'location.href = "/board"' in text
    assert 'location.href = "/"' not in text
    assert 'location.href = "/admin"' not in text


def test_board_unauthorized_stays_on_hub_login_next() -> None:
    text = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "/login?next=/board" in text
    assert '"/login?next=/"' not in text
    assert "'/login?next=/'" not in text


def test_login_treats_public_next_as_board() -> None:
    text = (STATIC / "login.html").read_text(encoding="utf-8")
    assert "function nextPath" in text
    assert 'requested === "/"' in text

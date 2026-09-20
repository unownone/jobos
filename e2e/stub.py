"""Seed stub Hub data for browser e2e or a local Compose stack.

Usage (Hub already running):

    uv run --directory board python ../e2e/stub.py --url http://127.0.0.1:18787
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESUME = ROOT / "fixtures" / "resume.pdf"

CANDIDATE = {
    "identity": {
        "full_name": "Jordan Lee",
        "preferred_name": "Jordan",
        "email": "jordan.e2e@example.test",
        "phone": "+1-555-0100",
        "location": "Bengaluru, India",
        "timezone": "Asia/Kolkata",
        "work_authorization": "India citizen; open to remote",
        "linkedin_url": "https://www.linkedin.com/in/jordan-e2e",
        "github_url": "https://github.com/jordan-e2e",
        "portfolio_url": "",
        "website": "",
    },
    "target": {
        "titles": ["Staff Software Engineer", "Senior Backend Engineer"],
        "locations": ["Remote", "Bengaluru"],
        "seniority": ["senior", "staff"],
        "domains": ["developer tools", "infra"],
        "remote": "required-or-hybrid",
        "must_haves": ["Writes production code"],
        "deal_breakers": ["Unpaid trial projects"],
    },
    "proof": {
        "headline": "Staff engineer who ships backends",
        "years_experience": 12,
        "stack": ["Python", "FastAPI", "Postgres"],
        "highlights": ["Owns a production service"],
        "do_not_claim": ["Anything not in this fixture"],
    },
    "materials": {"writing_voice": "Direct, specific, no fluff"},
}


def _request(
    url: str,
    method: str,
    path: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    req = urllib.request.Request(
        url.rstrip("/") + path,
        data=data,
        method=method,
        headers=headers or {},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return res.status, res.read(), dict(res.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def seed(url: str, username: str, password: str) -> dict[str, str]:
    status, body, _headers = _request(
        url,
        "POST",
        "/api/auth/signup",
        data=json.dumps({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
    )
    if status != 200:
        raise SystemExit(f"signup failed {status}: {body.decode('utf-8', 'replace')}")
    cookie = ""
    csrf = ""
    # urllib does not expose Set-Cookie easily across calls; login again with opener.
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    login = urllib.request.Request(
        url.rstrip("/") + "/api/auth/login",
        data=json.dumps({"username": username, "password": password}).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with opener.open(login, timeout=20) as res:
        res.read()
        for cookie_hdr in res.headers.get_all("Set-Cookie") or []:
            if cookie_hdr.startswith("hub_csrf="):
                csrf = cookie_hdr.split(";", 1)[0].split("=", 1)[1]
    put = urllib.request.Request(
        url.rstrip("/") + "/api/candidate",
        data=json.dumps(CANDIDATE).encode(),
        method="PUT",
        headers={"Content-Type": "application/json", "X-CSRF": csrf},
    )
    with opener.open(put, timeout=20) as res:
        if res.status != 200:
            raise SystemExit(f"candidate put failed {res.status}")
    pdf = RESUME.read_bytes()
    resume = urllib.request.Request(
        url.rstrip("/") + "/api/candidate/resume",
        data=pdf,
        method="PUT",
        headers={"Content-Type": "application/pdf", "X-CSRF": csrf},
    )
    with opener.open(resume, timeout=20) as res:
        if res.status != 200:
            raise SystemExit(f"resume put failed {res.status}")
    job = urllib.request.Request(
        url.rstrip("/") + "/api/jobs",
        data=json.dumps(
            {
                "id": f"e2e__stub-{username}",
                "company": "StubCo",
                "title": "Staff Software Engineer",
                "status": "discovered",
                "location": "Remote",
            }
        ).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-CSRF": csrf},
    )
    with opener.open(job, timeout=20) as res:
        if res.status not in {200, 201}:
            raise SystemExit(f"job create failed {res.status}: {res.read()!r}")
    return {"username": username, "password": password, "csrf": csrf, "cookie": cookie}


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed stub Hub tenant data")
    parser.add_argument("--url", default="http://127.0.0.1:18787")
    parser.add_argument("--username", default="stubadmin")
    parser.add_argument("--password", default="s3cret-stub")
    args = parser.parse_args()
    result = seed(args.url, args.username, args.password)
    print(json.dumps({"ok": True, **result, "password": "***"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

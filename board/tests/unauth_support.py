"""Helpers for unauthenticated security tests. Does not change app auth."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient

from app.constants import ROLES
from app.main import create_app
from app.settings import Settings

# Distinctive canaries: unauthenticated responses must never echo these.
JOB_ID = "remoteok__canary-secret-job"
JOB_COMPANY = "CanarySecretCorpZXQ"
JOB_TITLE = "Staff Canary Ranked Engineer"
APPLY_PACKET_STEP = "CANARY_APPLY_PACKET_STEP_UNIQUE"
PERSON_ID = "canaryco__hiring-manager-zxq"
PERSON_NAME = "Canary Hiring Manager ZXQ"
PERSON_EMAIL = "canary.hm.zxq@secret.test"
CANDIDATE_NAME = "Canary Candidate ZXQ"
CANDIDATE_EMAIL = "canary.candidate.zxq@secret.test"
CANDIDATE_PHONE = "+15550100CANARY"
CANDIDATE_LINKEDIN = "https://www.linkedin.com/in/canary-candidate-zxq"
MESSAGE_BODY = "Handoff CANARY_INBOX_BODY_ZXQ for CanarySecretCorpZXQ"
ADMIN_EMAIL = "owner@example.test"
ADMIN_PASSWORD = "correct-horse"

TOKENS = {role: f"canary-live-token-{role}-ZXQ9" for role in ROLES}

CANARY_CANDIDATE_YAML = f"""\
identity:
  full_name: "{CANDIDATE_NAME}"
  preferred_name: "Canary"
  email: "{CANDIDATE_EMAIL}"
  phone: "{CANDIDATE_PHONE}"
  location: "Remote"
  timezone: "UTC"
  work_authorization: "US citizen canary-auth-zxq"
  linkedin_url: "{CANDIDATE_LINKEDIN}"
  github_url: "https://github.com/canary-candidate-zxq"
  portfolio_url: ""
  website: ""

target:
  titles:
    - "Staff Software Engineer"
  seniority: ["staff"]
  domains: ["test"]
  locations:
    - "Remote"
  remote: "required"
  salary_floor_usd: 0
  visa_needs: false
  company_sizes: ["startup"]
  must_haves:
    - "Writes production code"
  deal_breakers:
    - "Unpaid trial projects"

proof:
  headline: "Canary fixture profile ZXQ"
  years_experience: 1
  stack: ["Python"]
  highlights:
    - "Fixture only"
  do_not_claim:
    - "Anything not in this fixture"

materials:
  resume_primary: "assets/resume/resume-primary.pdf"
  resume_variants: []
  writing_voice: "Direct"

constraints:
  max_discovers_per_cycle: 40
  max_shortlist_per_cycle: 12
  max_applies_per_day: 8
  max_outreach_touches_per_person: 2
  easy_apply_policy: "never during discovery"
"""

CANARY_RESUME_BYTES = (
    b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<</Type/Catalog>>endobj\n"
    b"Canary CV ZXQ for Canary Candidate ZXQ\ntrailer<<>>\n%%EOF\n"
)

SENSITIVE_SUBSTRINGS = (
    JOB_COMPANY,
    JOB_TITLE,
    APPLY_PACKET_STEP,
    PERSON_NAME,
    PERSON_EMAIL,
    CANDIDATE_NAME,
    CANDIDATE_EMAIL,
    CANDIDATE_PHONE,
    CANDIDATE_LINKEDIN,
    MESSAGE_BODY,
    *TOKENS.values(),
)

BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
}

PROTECTED_PAGES = (
    ("/", "job board page"),
    ("/admin", "admin dashboard"),
    ("/admin/invites", "admin invites page"),
    ("/admin/users", "admin user directory page"),
    ("/admin/memory", "memory pods page"),
    ("/onboarding", "candidate onboarding page"),
    ("/static/index.html", "job board static HTML"),
    ("/static/admin.html", "admin static HTML"),
    ("/static/users.html", "users directory static HTML"),
    ("/static/memory.html", "memory pods static HTML"),
    ("/static/onboarding.html", "candidate onboarding static HTML"),
)

PROTECTED_GETS = (
    ("/api/jobs", "job board list"),
    (f"/api/jobs/{JOB_ID}", "job board detail"),
    ("/api/jobs?status=apply_ready", "job board status/ranking filter"),
    ("/api/jobs?q=CanarySecretCorpZXQ", "job board search"),
    ("/api/people", "hiring-manager/people list"),
    (f"/api/people/{PERSON_ID}", "hiring-manager detail"),
    ("/api/candidate", "full candidate YAML / PII"),
    ("/api/candidate/public", "candidate public slice"),
    ("/api/candidate/resume", "candidate CV/resume PDF"),
    ("/api/candidate/status", "candidate status"),
    ("/api/candidate/template", "candidate YAML template"),
    ("/api/events", "internal job events log"),
    (f"/api/events?job_id={JOB_ID}", "per-job events"),
    ("/api/hygiene", "hygiene / duplicate ranking dashboard"),
    ("/api/metrics/summary", "token-burn metrics summary"),
    ("/api/metrics/token_burn", "token-burn rows"),
    ("/api/export/ledger?format=json", "ledger export JSON"),
    ("/api/messages", "inter-agent inbox"),
    ("/api/queue", "work queue listing"),
    ("/api/queue/mine", "claimed queue items"),
    ("/api/presence", "presence directory"),
    ("/api/users", "admin user directory API"),
    ("/api/agents", "agent directory"),
    ("/api/invites", "admin invites list"),
    ("/api/meta", "hub meta / catalog"),
    ("/api/whoami", "whoami principal"),
    ("/api/auth/me", "session /api/auth/me"),
    ("/api/onboarding", "onboarding pack (skills/MCP)"),
    ("/api/a2a/directory", "A2A peer directory"),
    ("/api/a2a/peers", "A2A peers"),
    ("/api/memory/recall", "memory recall"),
    ("/api/memory/items", "memory items"),
    ("/api/memory/pods", "memory pods"),
    ("/docs", "OpenAPI Swagger UI"),
    ("/redoc", "OpenAPI ReDoc"),
    ("/openapi.json", "OpenAPI schema dump"),
)


@dataclass(frozen=True)
class SeededHub:
    app: object
    authed: TestClient
    unauth: TestClient
    settings: Settings
    a2a_task_id: str


def role_headers(role: str, actor: str = "pytest") -> dict[str, str]:
    return {"X-Role": role, "X-Token": TOKENS[role], "X-Actor": actor}


def csrf_headers(client: TestClient, extra: dict[str, str] | None = None) -> dict[str, str]:
    csrf = client.cookies.get("hub_csrf") or ""
    headers = {"X-CSRF": csrf, "Content-Type": "application/json"}
    if extra:
        headers.update(extra)
    return headers


def hub_settings(tmp_path: Path) -> Settings:
    return Settings(
        board_dir=tmp_path,
        db_path=tmp_path / "board.db",
        host="127.0.0.1",
        port=8787,
        tokens=dict(TOKENS),
        public_url="https://hub.example.test",
        bootstrap_token="",
        env_path=tmp_path / ".env",
        tokens_json_path=tmp_path / "tokens.local.json",
        packs_dir=tmp_path / "packs",
    )


def write_canary_candidate(tmp_path: Path) -> None:
    dest = tmp_path / "profiles" / "candidate.yaml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(CANARY_CANDIDATE_YAML, encoding="utf-8")
    alt = tmp_path / "data" / "profiles" / "candidate.yaml"
    alt.parent.mkdir(parents=True, exist_ok=True)
    alt.write_text(CANARY_CANDIDATE_YAML, encoding="utf-8")
    (tmp_path / "candidate-resume.pdf").write_bytes(CANARY_RESUME_BYTES)


def bootstrap_admin(client: TestClient) -> None:
    token = client.app.state.bootstrap_token
    res = client.post(
        "/api/auth/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert res.status_code == 200, res.text


def seed_sensitive_records(client: TestClient) -> str:
    """Create job, person, metrics, and an A2A task. Returns A2A task id (may be empty)."""
    created = client.post(
        "/api/jobs",
        headers=role_headers("discovery"),
        json={
            "id": JOB_ID,
            "company": JOB_COMPANY,
            "title": JOB_TITLE,
            "apply_url": "https://jobs.example.test/canary-staff",
            "sources": ["remoteok"],
            "status": "apply_ready",
            "score": 5,
            "apply_packet": {
                "url": "https://jobs.example.test/canary-staff",
                "steps": [APPLY_PACKET_STEP],
            },
            "notes": "canary job for unauth leak tests",
        },
    )
    assert created.status_code == 201, created.text

    person = client.post(
        "/api/people",
        headers=role_headers("outreach"),
        json={
            "id": PERSON_ID,
            "name": PERSON_NAME,
            "title": "Engineering Manager",
            "company": JOB_COMPANY,
            "job_id": JOB_ID,
            "email": PERSON_EMAIL,
            "do_not_contact": False,
            "touches": [],
        },
    )
    assert person.status_code == 201, person.text

    burn = client.post(
        "/api/metrics/token_burn",
        headers=role_headers("discovery"),
        json={
            "tool_name": "canary-exa-search",
            "skill": "job-discovery",
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "job_id": JOB_ID,
        },
    )
    assert burn.status_code == 201, burn.text

    a2a = client.post(
        "/a2a",
        headers=role_headers("discovery"),
        json={
            "jsonrpc": "2.0",
            "id": "seed-task",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "messageId": "canary-msg-1",
                    "parts": [
                        {"kind": "text", "text": MESSAGE_BODY},
                        {
                            "kind": "data",
                            "data": {
                                "type": "handoff",
                                "to_track": "application",
                                "job_id": JOB_ID,
                            },
                        },
                    ],
                }
            },
        },
    )
    task_id = ""
    if a2a.status_code == 200:
        payload = a2a.json()
        result = payload.get("result") if isinstance(payload, dict) else None
        if isinstance(result, dict):
            task_id = str(result.get("id") or "")
    return task_id


def make_seeded_hub(tmp_path: Path) -> SeededHub:
    write_canary_candidate(tmp_path)
    settings = hub_settings(tmp_path)
    app = create_app(settings)
    authed = TestClient(app)
    unauth = TestClient(app, follow_redirects=False)
    bootstrap_admin(authed)
    task_id = seed_sensitive_records(authed)
    return SeededHub(
        app=app,
        authed=authed,
        unauth=unauth,
        settings=settings,
        a2a_task_id=task_id,
    )


def assert_unauthenticated_denied(response, *, what: str) -> None:
    """Unauthenticated access must be 401/403 or a redirect to /login, with no canaries."""
    status = response.status_code
    location = response.headers.get("location") or response.headers.get("Location") or ""
    redirected_to_login = status in {301, 302, 303, 307, 308} and "/login" in location.lower()
    denied = status in {401, 403} or redirected_to_login
    body = response.content.decode("utf-8", errors="replace") if response.content else ""
    leaked = [item for item in SENSITIVE_SUBSTRINGS if item and item in body]
    header_blob = " ".join(f"{k}: {v}" for k, v in response.headers.items())
    leaked_headers = [item for item in SENSITIVE_SUBSTRINGS if item and item in header_blob]
    assert denied, (
        f"unauthenticated {what} returned {status} "
        f"(expected 401/403 or redirect to /login); "
        f"Location={location!r}; body starts {body[:400]!r}"
    )
    assert not leaked, (
        f"unauthenticated {what} leaked sensitive payload {leaked!r} "
        f"with status {status}"
    )
    assert not leaked_headers, (
        f"unauthenticated {what} leaked sensitive values in headers {leaked_headers!r}"
    )


def secret_like_patterns() -> tuple[str, ...]:
    return (
        r"jh_agt_[A-Za-z0-9_-]{8,}",
        r"jh_own_[A-Za-z0-9_-]{8,}",
        r"jh_boot_[A-Za-z0-9_-]{8,}",
        r"sk-[A-Za-z0-9]{20,}",
        r"BOARD_TOKEN_[A-Z]+=\S+",
        r"HUB_BOOTSTRAP_TOKEN=\S+",
        r"NEXT_PUBLIC_[A-Z0-9_]+=(?!\$\{)[^\s\"']+",
    )

"""Unauthenticated HTTP access to sensitive Job Hub APIs must be denied.

Covers job board (lists, details, ranking/filters), people/PII, candidate CVs,
admin/internal dumps, queue, messages, export, metrics, and A2A task fetch.
Failures name the surface that leaked (status 200 with payload, or canary in body).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unauth_support import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    APPLY_PACKET_STEP,
    CANDIDATE_EMAIL,
    JOB_COMPANY,
    JOB_ID,
    MESSAGE_BODY,
    PERSON_EMAIL,
    PERSON_ID,
    PROTECTED_GETS,
    SeededHub,
    assert_unauthenticated_denied,
    make_seeded_hub,
    role_headers,
)


@pytest.fixture()
def seeded(tmp_path: Path) -> SeededHub:
    return make_seeded_hub(tmp_path)


@pytest.mark.parametrize(
    "path,what",
    PROTECTED_GETS,
    ids=[item[1].replace(" ", "-") for item in PROTECTED_GETS],
)
def test_unauthenticated_get_sensitive_api_is_denied(
    seeded: SeededHub,
    path: str,
    what: str,
) -> None:
    res = seeded.unauth.get(path)
    assert_unauthenticated_denied(res, what=f"GET {path} ({what})")
    if res.status_code == 200:
        raise AssertionError(
            f"unauthenticated {what} returned 200 with body {res.text[:400]!r}"
        )


def test_unauthenticated_job_board_list_does_not_return_jobs(seeded: SeededHub) -> None:
    res = seeded.unauth.get("/api/jobs")
    assert_unauthenticated_denied(res, what="job board list /api/jobs")
    if res.headers.get("content-type", "").startswith("application/json"):
        payload = res.json()
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        assert not jobs, (
            f"unauthenticated job board list returned 200 with jobs: {jobs!r}"
        )


def test_unauthenticated_job_detail_does_not_return_apply_packet(
    seeded: SeededHub,
) -> None:
    res = seeded.unauth.get(f"/api/jobs/{JOB_ID}")
    assert_unauthenticated_denied(res, what=f"job board detail /api/jobs/{JOB_ID}")
    assert APPLY_PACKET_STEP not in (res.text or "")


def test_unauthenticated_ranked_jobs_query_is_denied(seeded: SeededHub) -> None:
    res = seeded.unauth.get("/api/jobs", params={"status": "apply_ready", "q": JOB_COMPANY})
    assert_unauthenticated_denied(
        res, what="job board ranked/status+search GET /api/jobs?status=apply_ready"
    )


def test_unauthenticated_cannot_create_or_mutate_jobs(seeded: SeededHub) -> None:
    created = seeded.unauth.post(
        "/api/jobs",
        json={"company": "UnauthCorp", "title": "Should Fail", "id": "remoteok__unauth-write"},
    )
    assert_unauthenticated_denied(created, what="POST /api/jobs (create job)")
    patched = seeded.unauth.patch(
        f"/api/jobs/{JOB_ID}",
        json={"notes": "unauth overwrite"},
    )
    assert_unauthenticated_denied(patched, what=f"PATCH /api/jobs/{JOB_ID}")
    deleted = seeded.unauth.delete(f"/api/jobs/{JOB_ID}")
    assert_unauthenticated_denied(deleted, what=f"DELETE /api/jobs/{JOB_ID}")
    still = seeded.authed.get(f"/api/jobs/{JOB_ID}", headers=role_headers("admin"))
    assert still.status_code == 200, still.text
    assert still.json()["job"]["company"] == JOB_COMPANY


def test_unauthenticated_people_list_does_not_return_contacts(seeded: SeededHub) -> None:
    res = seeded.unauth.get("/api/people")
    assert_unauthenticated_denied(res, what="people/hiring-manager list /api/people")
    assert PERSON_EMAIL not in (res.text or "")


def test_unauthenticated_cannot_write_people(seeded: SeededHub) -> None:
    res = seeded.unauth.post(
        "/api/people",
        json={"name": "Unauth Person", "company": JOB_COMPANY, "id": "unauth__person"},
    )
    assert_unauthenticated_denied(res, what="POST /api/people")


def test_unauthenticated_candidate_yaml_and_resume_are_denied(seeded: SeededHub) -> None:
    yaml_res = seeded.unauth.get("/api/candidate")
    assert_unauthenticated_denied(yaml_res, what="GET /api/candidate (full YAML PII)")
    assert CANDIDATE_EMAIL not in (yaml_res.text or "")
    public_res = seeded.unauth.get("/api/candidate/public")
    assert_unauthenticated_denied(public_res, what="GET /api/candidate/public")
    status_res = seeded.unauth.get("/api/candidate/status")
    assert_unauthenticated_denied(status_res, what="GET /api/candidate/status")
    resume = seeded.unauth.get("/api/candidate/resume")
    assert_unauthenticated_denied(resume, what="GET /api/candidate/resume (CV PDF)")
    content_type = resume.headers.get("content-type", "")
    assert "pdf" not in content_type.lower(), (
        f"unauthenticated candidate resume returned PDF content-type {content_type}"
    )


def test_unauthenticated_cannot_overwrite_candidate_or_resume(seeded: SeededHub) -> None:
    put_yaml = seeded.unauth.put(
        "/api/candidate",
        content=b"identity:\n  full_name: hacked\n",
        headers={"Content-Type": "text/yaml"},
    )
    assert_unauthenticated_denied(put_yaml, what="PUT /api/candidate")
    put_pdf = seeded.unauth.put(
        "/api/candidate/resume",
        content=b"%PDF-1.4 hacked",
        headers={"Content-Type": "application/pdf"},
    )
    assert_unauthenticated_denied(put_pdf, what="PUT /api/candidate/resume")


def test_unauthenticated_admin_internal_dumps_are_denied(seeded: SeededHub) -> None:
    for path, what in (
        ("/api/users", "admin user directory"),
        ("/api/invites", "admin invites"),
        ("/api/agents", "agent directory"),
        ("/api/hygiene", "hygiene dashboard"),
        ("/api/export/ledger?format=json", "ledger export"),
        ("/api/metrics/summary", "metrics summary"),
        ("/api/events", "events log"),
        ("/api/presence", "presence directory"),
    ):
        res = seeded.unauth.get(path)
        assert_unauthenticated_denied(res, what=f"GET {path} ({what})")


def test_unauthenticated_queue_and_messages_are_denied(seeded: SeededHub) -> None:
    listed = seeded.unauth.get("/api/queue")
    assert_unauthenticated_denied(listed, what="GET /api/queue")
    mine = seeded.unauth.get("/api/queue/mine")
    assert_unauthenticated_denied(mine, what="GET /api/queue/mine")
    claim = seeded.unauth.post("/api/queue/claim", json={"limit": 1})
    assert_unauthenticated_denied(claim, what="POST /api/queue/claim")
    inbox = seeded.unauth.get("/api/messages")
    assert_unauthenticated_denied(inbox, what="GET /api/messages")
    sent = seeded.unauth.post(
        "/api/messages",
        json={"body": MESSAGE_BODY, "to_track": "application", "type": "note"},
    )
    assert_unauthenticated_denied(sent, what="POST /api/messages")


def test_unauthenticated_a2a_task_get_does_not_return_inbox_payload(
    seeded: SeededHub,
) -> None:
    task_id = seeded.a2a_task_id
    assert task_id, "expected seeded A2A task so unauth fetch can be asserted"
    res = seeded.unauth.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "leak-check",
            "method": "tasks/get",
            "params": {"id": task_id},
        },
    )
    body = res.text or ""
    denied_http = res.status_code in {401, 403}
    rpc_error = False
    if res.headers.get("content-type", "").startswith("application/json"):
        payload = res.json()
        if isinstance(payload, dict) and payload.get("error"):
            rpc_error = True
            result = payload.get("result")
            assert result is None or result == {}, (
                f"unauthenticated A2A tasks/get returned error plus result {result!r}"
            )
        elif isinstance(payload, dict) and payload.get("result"):
            raise AssertionError(
                "unauthenticated A2A tasks/get returned 200 with task result "
                f"(leaked inbox/job payload): {payload['result']!r}"
            )
    assert denied_http or rpc_error, (
        f"unauthenticated A2A tasks/get returned {res.status_code} without auth error; "
        f"body {body[:400]!r}"
    )
    assert JOB_COMPANY not in body
    assert MESSAGE_BODY not in body


def test_unauthenticated_a2a_tasks_list_and_cancel_are_denied(seeded: SeededHub) -> None:
    listed = seeded.unauth.post(
        "/a2a",
        json={"jsonrpc": "2.0", "id": "1", "method": "tasks/list", "params": {}},
    )
    body = listed.text or ""
    if listed.status_code == 200:
        payload = listed.json()
        if isinstance(payload, dict) and payload.get("result"):
            raise AssertionError(
                f"unauthenticated A2A tasks/list returned task list: {payload['result']!r}"
            )
        if not (isinstance(payload, dict) and payload.get("error")):
            raise AssertionError(
                f"unauthenticated A2A tasks/list returned {listed.status_code} {body[:300]!r}"
            )
    else:
        assert listed.status_code in {401, 403}, listed.text
    assert JOB_COMPANY not in body

    if seeded.a2a_task_id:
        cancel = seeded.unauth.post(
            "/a2a",
            json={
                "jsonrpc": "2.0",
                "id": "2",
                "method": "tasks/cancel",
                "params": {"id": seeded.a2a_task_id},
            },
        )
        cancel_body = cancel.text or ""
        if cancel.status_code == 200:
            payload = cancel.json()
            if isinstance(payload, dict) and payload.get("result"):
                raise AssertionError(
                    "unauthenticated A2A tasks/cancel succeeded and returned "
                    f"{payload['result']!r}"
                )
            if not (isinstance(payload, dict) and payload.get("error")):
                raise AssertionError(
                    f"unauthenticated A2A tasks/cancel returned 200 {cancel_body[:300]!r}"
                )
        else:
            assert cancel.status_code in {401, 403}, cancel.text


def test_unauthenticated_openapi_docs_are_denied(seeded: SeededHub) -> None:
    for path, what in (
        ("/docs", "Swagger UI /docs"),
        ("/redoc", "ReDoc /redoc"),
        ("/openapi.json", "OpenAPI schema /openapi.json"),
    ):
        res = seeded.unauth.get(path)
        assert_unauthenticated_denied(res, what=what)


def test_authenticated_control_candidate_and_people_still_work(seeded: SeededHub) -> None:
    login = seeded.authed.post(
        "/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert login.status_code == 200, login.text
    public = seeded.authed.get("/api/candidate/public")
    assert public.status_code == 200, public.text
    people = seeded.authed.get("/api/people", headers=role_headers("outreach"))
    assert people.status_code == 200, people.text
    ids = [row.get("id") for row in people.json().get("people", [])]
    assert PERSON_ID in ids
    jobs = seeded.authed.get("/api/jobs", headers=role_headers("apply"))
    assert jobs.status_code == 200
    assert any(job["id"] == JOB_ID for job in jobs.json()["jobs"])


def test_unauthenticated_cannot_write_registry_or_memory(seeded: SeededHub) -> None:
    created = seeded.unauth.post(
        "/api/registry/skills",
        json={
            "slug": "unauth-hijack",
            "name": "Hijack",
            "role": "apply",
            "tags": ["apply"],
            "body": "should not land",
        },
    )
    assert_unauthenticated_denied(created, what="POST /api/registry/skills")
    recorded = seeded.unauth.post(
        "/api/registry/recordings",
        json={"slug": "unauth-rec", "name": "Hijack", "role": "apply", "tags": ["apply"], "body": "nope"},
    )
    assert_unauthenticated_denied(recorded, what="POST /api/registry/recordings")
    seed = seeded.unauth.post("/api/registry/seed")
    assert_unauthenticated_denied(seed, what="POST /api/registry/seed")
    mem = seeded.unauth.post(
        "/api/memory/items",
        json={
            "pod": "track",
            "kind": "portal_quirk",
            "title": "Unauth greenhouse quirk",
            "body": "Unauthenticated write of a durable portal quirk must be rejected by the Hub.",
        },
    )
    assert_unauthenticated_denied(mem, what="POST /api/memory/items")
    solid = seeded.unauth.post("/api/memory/items/mem_missing/solidify", json={})
    assert_unauthenticated_denied(solid, what="POST /api/memory/items/{id}/solidify")

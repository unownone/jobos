# Browser e2e (Playwright)

Live frontend + backend coverage for Job Hub. These tests drive a **real Hub**
(Docker Compose when Docker is available, otherwise local uvicorn + Postgres)
and a **real browser**. They are not the in-process FastAPI `pytest -m e2e`
suite in `board/tests/`.

## Run

From repo root:

```bash
bash scripts/e2e_browser.sh
```

That script:

1. Starts `docker-compose.e2e.yml` (`http://127.0.0.1:18787`) when Docker works.
2. Falls back to uvicorn + embedded Postgres when Docker is missing.
3. Installs the `browser` uv group and Chromium (or uses system Chrome).
4. Runs Playwright against every Hub flow listed in [`FLOWS.md`](FLOWS.md).

Optional env:

| Variable | Meaning |
| --- | --- |
| `E2E_HUB_URL` | Use an already-running Hub; skip start |
| `E2E_BACKEND=local` | Force uvicorn even if Docker exists |
| `E2E_BACKEND=external` | URL only; do not start or tear down |
| `E2E_KEEP=1` | Leave Compose up after tests |
| `E2E_BROWSER_CHANNEL=chrome` | Use system Chrome |

Manual Compose:

```bash
docker compose -f docker-compose.e2e.yml -p jobos-e2e up -d --build
# optional stub tenant
uv run --directory board python ../e2e/stub.py --url http://127.0.0.1:18787
E2E_HUB_URL=http://127.0.0.1:18787 E2E_BACKEND=external bash scripts/e2e_browser.sh
docker compose -f docker-compose.e2e.yml -p jobos-e2e down -v
```

## What it proves

- Admin signup → onboarding → **session stays alive** (no auto-logout).
- Candidate form **prefills** after save.
- Workers join a track, post jobs, claim queue work, heartbeat; admin sees them.
- A second admin cannot read or write the first tenant’s jobs or profile.

See [`FLOWS.md`](FLOWS.md) for the page/API inventory mapped to tests.

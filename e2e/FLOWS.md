# Hub flow coverage

Each live Hub surface has a Playwright owner. In-process FastAPI tests in
`server/` Go tests stay responsible for unit and HTTP contract branches.

## Frontend pages

| Page | Flow | Test |
| --- | --- | --- |
| `/` | Public landing; session CTA becomes Open board | `test_public.py`, `test_onboarding.py` |
| `/start` | Public get-started | `test_public.py` |
| `/login` | Login, signup, bad password, next=/board, existing admin | `test_onboarding.py`, `test_public.py` |
| `/admin/signup` | Leaves once any admin exists | `test_onboarding.py` |
| `/onboarding` | Identity → targets → proof → resume; validation; prefill | `test_onboarding.py` |
| `/home` | Funnel, agents, today, oldest pipeline job | `test_admin_shell.py` |
| `/board` | Session, jobs list, search, ticket patch/pause/resume | `test_admin_shell.py`, `test_worker.py` |
| `/admin` | Create invite, copy join URL, revoke, coming-soon stubs | `test_admin_shell.py`, `test_worker.py` |
| `/admin/users` | Directory after worker heartbeat | `test_worker.py` |
| `/admin/data` | jobs / people / candidate / skills / mcps / memory tabs | `test_worker.py`, `test_admin_shell.py` |
| `/admin/skills` | Filter + GitHub re-seed | `test_admin_shell.py` |
| `/admin/memory` | Add + edit fact | `test_admin_shell.py` |
| `/join/{id}` | Blocked until onboarded; register worker; show API key once | `test_worker.py` |

## Backend families (live server)

| Family | Covered by |
| --- | --- |
| Auth signup/login/logout/me | `test_onboarding.py` |
| Candidate PUT/GET JSON/resume/status | `server/` HTTP tests + Hub candidate routes |
| Jobs create/list/get isolation | `test_worker.py`, `test_isolation.py` |
| Queue push/claim/ack (+ catalog.refresh) | `test_worker.py` |
| Presence heartbeat + directory | `test_worker.py` |
| People create | `test_worker.py` |
| Memory write + recall | `test_worker.py`, `test_admin_shell.py` |
| Registry list/seed | `test_admin_shell.py` |
| Messages | `test_admin_shell.py` |
| Export ledger | `test_admin_shell.py` |
| Onboarding pack / skills | `test_admin_shell.py` |
| Hygiene / import / events / whoami | `test_admin_shell.py` |
| Token-burn metrics | `test_admin_shell.py` |
| A2A cards + directory | `test_public.py`, `test_admin_shell.py` |
| Briefing `/llms.txt` `/agents.txt` | `test_public.py` |
| Unauth gate | `server/` HTTP tests for unauth gates |

## Isolation

`test_isolation.py` creates two admins in separate browser contexts and asserts
jobs and candidate fields never leak across tenants.

## Not a browser page (API-only, covered by Go Hub tests)

A2A JSON-RPC send, recording proctor/promote/decline, pack rebuild, compat
X-Role tokens, OpenTelemetry, SQL migrations. Those stay in-process e2e/unit.

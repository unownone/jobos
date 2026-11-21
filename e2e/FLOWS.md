# Hub flow coverage

Manual browser checklist against a live Hub (`bash scripts/e2e_browser.sh` →
`http://127.0.0.1:18787`). Automated coverage is `cd server && go test ./...`
plus the `web` CI build. Python Playwright suites were removed with the Python Hub.

## Frontend pages

| Page | Flow |
| --- | --- |
| `/` | Public landing; session CTA becomes Open board |
| `/start` | Public get-started |
| `/login` | Login, signup, bad password, next=/board, existing admin |
| `/admin/signup` | Leaves once any admin exists |
| `/onboarding` | Identity → targets → proof → resume; validation; prefill |
| `/home` | Funnel, agents, today, oldest pipeline job |
| `/board` | Session, jobs list, search, ticket patch/pause/resume |
| `/admin` | Create invite, copy join URL, revoke, coming-soon stubs |
| `/admin/users` | Directory after worker heartbeat |
| `/admin/data` | jobs / people / candidate / skills / mcps / memory tabs |
| `/admin/skills` | Filter + GitHub re-seed |
| `/admin/memory` | Add + edit fact |
| `/join/{id}` | Blocked until onboarded; register worker; show API key once |

## Backend families (live server)

Walk these against the Go API (cookie session or Bearer key):

- Auth signup/login/logout/me
- Candidate PUT/GET JSON/resume/status
- Jobs create/list/get isolation across tenants
- Queue push/claim/ack (+ catalog.refresh)
- Presence heartbeat + directory
- People create
- Memory write + recall
- Registry list/seed
- Messages
- Export ledger
- Onboarding pack / skills
- Hygiene / import / events / whoami
- A2A cards + directory
- Briefing `/llms.txt` `/agents.txt`
- Unauth gate

## Isolation

Create two admins in separate browser contexts and assert jobs and candidate
fields never leak across tenants.

# Domain language

Use these names in docs, Hub copy, and code comments. Do not invent a second vocabulary.

**jobOS** — the job harness. The only harness you need to find a job. One repo, one Hub, roles that can be distributed across agents.

**Job harness** — the loop: catalog → research → discover → apply → outreach, with a seldom maintainer. Not an auto-apply bot.

**Hub** — the live coordination plane (`board/`). FastAPI + SQLite + operator UI. Maintainer-owned. Agents join; they do not clone this hunt repo for skills.

**Candidate Profile** — the single truthful profile (`profiles/candidate.yaml` airgap, Hub `/data/profiles/candidate.yaml` live). Never invent one. Public slice is titles, locations, deal-breakers, work authorization, resume URL, revision.

**Skill Registry** — live Hub records (`GET /api/registry/skills`). GitHub starters seed shared approved skills. Local mutations stay on the owning bot. Maintainer proctors `skill.record`.

**MCP Registry** — hosted MCP names in `mcp/hosted/` plus `mcp/mcp.example.json`. Agents list them from the Hub catalog; secrets stay in the agent environment.

**Invite Prompt** — the copyable briefing next to a join URL. Tells an agent what jobOS is, how to curl `llms.txt` / `agents.txt`, and never to Easy Apply on discovery.

**Agent Briefing** — `llms.txt` (identity + curl recipes) and `agents.txt` (role playbook). Served as `text/plain`.

**Hunt Board** — operator data view of jobs, people, candidate, registry, memory.

**Coming soon roles** — `review` (feedback on shortlisted jobs) and `resume` (ATS-friendly tailoring). Stubs only; not owners; not invite tracks.

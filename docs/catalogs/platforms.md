# Platform catalog

Discovery coverage map. Mark a row `active` in your fork when a bot actually runs it. Default here is the intended template set.

Legend for `kind`:

- `board` — public or authenticated job listings
- `career` — company career site
- `network` — talent marketplace; often apply-to-join, not a JD
- `feed` — public API / RSS
- `dork` — search operators over public ATS pages

| id | name | kind | start url | auth | discovery method | apply notes |
| --- | --- | --- | --- | --- | --- | --- |
| linkedin | LinkedIn Jobs | board | https://www.linkedin.com/jobs | session | Official search UI / existing LinkedIn skills. **List and packet only.** | Easy Apply is apply-role only |
| indeed | Indeed | board | https://www.indeed.com | OAuth MCP | Official Indeed MCP when available | Packet with job detail URL |
| wellfound | Wellfound | board | https://wellfound.com | session optional | Site search; no official public API | Startup JDs; watch duplicates with LinkedIn |
| workatastartup | Work at a Startup | board | https://www.workatastartup.com | none/session | `workatastartup-mcp` or site | YC companies; apply URL in packet |
| google_jobs | Google Jobs | board | Google Jobs UI | none | Search + “Jobs” pack | Always store the employer apply URL, not only the Google card |
| google_dorks | Google ATS dorks | dork | web search | none | Operators in this file | High signal for Greenhouse/Lever/Ashby/Workday |
| remoteok | RemoteOK | feed | https://remoteok.com | none | `https://remoteok.com/api` | Credit RemoteOK; use original job URL |
| weekday | Weekday | board | https://jobs.weekday.works | none/session | Public job pages / Workable | Often India + remote listings |
| rororemote | Roro Remote | board | confirm in fork | unknown | Treat as named portal; record actual URL when found | If no board, `apply_kind: outreach_only` |
| flexiple | Flexiple | network | https://flexiple.com | profile | Open roles if listed; else network apply | Often marketplace matching |
| turing | Turing | network | https://www.turing.com | profile | Vetting flow, not a classic board | Packet = how to pass intake |
| bairesdev | BairesDev | network | https://www.bairesdev.com | profile | Careers + recruiter path | Often outreach + careers page |
| toptal | Toptal | network | https://www.toptal.com | profile | Apply to network | Screening process is the “apply” |
| lemonio | Lemon.io | network | https://lemon.io | profile | Apply to network | Matching, not a JD board |
| amazon | Amazon Jobs | career | https://www.amazon.jobs | account | See big-tech catalog | Workday-ish; packet must include req id |
| microsoft | Microsoft Careers | career | https://jobs.careers.microsoft.com | account | big-tech catalog | |
| google | Google Careers | career | https://www.google.com/about/careers | account | big-tech catalog | |
| uber | Uber Careers | career | https://www.uber.com/careers | account | big-tech catalog | |

Add rows in your fork. Do not delete template rows; mark `ignored` in a local note instead.

MCP / skill coverage for these rows (what exists, what is a gap, what to install next) lives in [`skills-and-mcps.md`](skills-and-mcps.md) and [`docs/research/platform-mcp-build-plan.md`](../research/platform-mcp-build-plan.md). Do not invent an MCP because a platform is listed here.

## Google dork patterns

Use these as discovery queries. Swap the title fragment for the candidate’s targets. This is ordinary public search, not an exploit.

```
site:boards.greenhouse.io "{title}"
site:jobs.lever.co "{title}"
site:jobs.ashbyhq.com "{title}"
site:*.myworkdayjobs.com "{title}"
site:apply.workable.com "{title}"
site:jobs.smartrecruiters.com "{title}"
site:amazon.jobs "{title}"
site:jobs.careers.microsoft.com "{title}"
site:careers.google.com "{title}"
site:uber.com/careers "{title}"
"{title}" ("we're hiring" OR "job id" OR "requisition") after:2026-01-01
```

Always open the **employer** page before shortlisting. Google cards go stale.

## LinkedIn Jobs

Discovery may:

- Search, filter, capture job id, title, company, location, apply type, listing URL
- Save a screenshot or text of the JD into the job YAML `source_excerpt`

Discovery may not:

- Click Easy Apply
- Submit the Easy Apply modal
- Message the poster

If a listing is Easy Apply, set `apply_kind: linkedin_easy_apply` in the packet so the apply bot knows.

## Indeed

Preferred: official Indeed MCP (OAuth). Tools typically: Job Search, Job Detail, Get Company Data, Get Resume.

If the MCP is Claude-connector-only in your client, record that in the MCP catalog and fall back to public job URLs + research.

## RemoteOK

```
GET https://remoteok.com/api
GET https://remoteok.com/api?tag=dev
```

No auth. Credit RemoteOK and keep the original URL. First element of the JSON feed is metadata — skip it.

## Networks without a board

Toptal, Lemon.io, Turing, Flexiple, BairesDev (often):

```yaml
apply_kind: network
apply_packet:
  url: "https://..."
  steps:
    - "Create profile with candidate.yaml identity"
    - "Upload resume-primary.pdf"
    - "Complete screening as documented"
```

Do not pretend there is a JD. Score the **network** against the candidate’s goals.

## Roro Remote

The name is in the original coverage list. Confirm the live URL in the first catalog pass and write it here. Until then, discovery should search the web for the candidate’s titles plus `Roro Remote` and either:

- Add a real board URL, or
- Mark the source `outreach_only`

## Dedup keys

1. Normalized apply URL (strip tracking query params)
2. Else `(company_normalized, title_normalized, location_normalized)`
3. Else ATS req id if present

When merging, keep the richest JD and union the source list (`sources: [linkedin, indeed]`).

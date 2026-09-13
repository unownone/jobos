# Starter skills

GitHub copies of tagged, reproducible playbooks. Hub boot and pack rebuild **seed** these into the live registry (`scope=shared`, `origin=github`).

These files are not Cursor-loadable OS skills. Role playbooks in `skills/*/SKILL.md` stay the agent entrypoints. When Hub is up, those roles **select a matching tagged skill** from `GET /api/registry/skills`.

Outline: [`docs/catalogs/skill-outline.md`](../../docs/catalogs/skill-outline.md).

| slug | tag | role |
| --- | --- | --- |
| `source-linkedin` | source | discovery |
| `source-indeed` | source | discovery |
| `source-wellfound` | source | discovery |
| `source-workatastartup` | source | discovery |
| `source-google-dorks` | source | discovery |
| `source-remoteok` | source | discovery |
| `source-hiringcafe` | source | discovery |
| `source-weekday` | source | discovery |
| `source-rororemote` | source | discovery |
| `source-big-tech` | source | discovery |
| `source-network` | source | discovery |
| `apply-greenhouse` | apply | apply |
| `apply-lever` | apply | apply |
| `apply-ashby` | apply | apply |
| `apply-workday` | apply | apply |
| `apply-linkedin-easy-apply` | apply | apply |
| `apply-generic-ats` | apply | apply |
| `apply-network` | apply | apply |
| `outreach-email` | outreach | outreach |
| `outreach-linkedin-dm` | outreach | outreach |

Do not put secrets here. Tenant-specific mutations stay **local** in the Hub registry until maintainer proctors a recording.

# Starter skill index

GitHub copies seeded into the Hub registry. Cursor still loads `skills/<name>/SKILL.md` for the role.

| slug | role | tags | platform | match |
| --- | --- | --- | --- | --- |
| [source-linkedin](source-linkedin.yaml) | discovery | source, board, linkedin | linkedin | `*.linkedin.com/jobs/*` |
| [source-indeed](source-indeed.yaml) | discovery | source, board, indeed | indeed | `*.indeed.com/*` |
| [source-wellfound](source-wellfound.yaml) | discovery | source, board, wellfound | wellfound | `wellfound.com/*` |
| [source-workatastartup](source-workatastartup.yaml) | discovery | source, board, y-combinator | workatastartup | `*.workatastartup.com/*` |
| [source-google-dorks](source-google-dorks.yaml) | discovery | source, dork, ats | google_dorks | Greenhouse / Lever / Ashby / Workday dorks |
| [source-remoteok](source-remoteok.yaml) | discovery | source, feed, remoteok | remoteok | `remoteok.com/api*` |
| [source-hiringcafe](source-hiringcafe.yaml) | discovery | source, board, hiringcafe | hiringcafe | `hiringcafe.com/jobs/*` |
| [source-weekday](source-weekday.yaml) | discovery | source, board, weekday | weekday | `jobs.weekday.works/*`, Workable |
| [source-rororemote](source-rororemote.yaml) | discovery | source, board, rororemote | rororemote | named portal; else `outreach_only` |
| [source-big-tech](source-big-tech.yaml) | discovery | source, career, big-tech | amazon | Amazon / Microsoft / Google / Uber careers + req id |
| [source-network](source-network.yaml) | discovery | source, network | network | Flexiple, Turing, Toptal, Lemon.io, BairesDev |
| [apply-greenhouse](apply-greenhouse.yaml) | apply | apply, ats, greenhouse | greenhouse | `boards.greenhouse.io/*` |
| [apply-lever](apply-lever.yaml) | apply | apply, ats, lever | lever | `jobs.lever.co/*` |
| [apply-ashby](apply-ashby.yaml) | apply | apply, ats, ashby | ashby | `jobs.ashbyhq.com/*` |
| [apply-workday](apply-workday.yaml) | apply | apply, ats, workday | workday | `*.myworkdayjobs.com/*` |
| [apply-linkedin-easy-apply](apply-linkedin-easy-apply.yaml) | apply | apply, linkedin, ats | linkedin | `apply_kind: linkedin_easy_apply` |
| [apply-generic-ats](apply-generic-ats.yaml) | apply | apply, ats | other | obscure / unknown ATS |
| [apply-network](apply-network.yaml) | apply | apply, network | network | `apply_kind: network` |
| [outreach-email](outreach-email.yaml) | outreach | outreach, mail | mail | Gmail draft + PDF |
| [outreach-linkedin-dm](outreach-linkedin-dm.yaml) | outreach | outreach, linkedin | linkedin | short chat ask, no PDF |

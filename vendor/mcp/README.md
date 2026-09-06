# Vendored local MCP servers

These are **downloaded copies** of small, no-key (or optional-key) MCP servers so a clone of Job Apply OS can run discovery without hunting GitHub.

| Dir | Upstream | License | Launch |
| --- | --- | --- | --- |
| `workatastartup-mcp` | [MIt9/workatastartup-mcp](https://github.com/MIt9/workatastartup-mcp) | MIT | `bash scripts/mcp/workatastartup.sh` |
| `ats-jobs-mcp` | [groundtruthtools/ats-jobs-mcp](https://github.com/groundtruthtools/ats-jobs-mcp) | MIT | `bash scripts/mcp/ats-jobs.sh` |
| `job-scout-mcp` | [pabnatanawan87/job-scout-mcp](https://github.com/pabnatanawan87/job-scout-mcp) | MIT | `bash scripts/mcp/job-scout.sh` |

Pins: [`PINNED.txt`](PINNED.txt).

Do **not** vendor LinkedIn session/cookie servers, Apify scrapers, or recruiter-side Harvest APIs.

Refresh (maintainer):

```bash
bash scripts/setup_vendor_mcps.sh --refresh
```

`node_modules` and `.venv` stay gitignored. First launch of a Python server uses `uv run` (downloads deps into that package’s `.venv`). Job-scout needs `npm ci` once; `setup_vendor_mcps.sh` does that.

Hosted MCPs (Exa, Gmail, Hunter, …) are **not** here. Copy-paste configs: [`mcp/hosted/`](../../mcp/hosted/) and [`mcp/SETUP.md`](../../mcp/SETUP.md).

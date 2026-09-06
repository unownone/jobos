# Local MCP pins (not source trees)

Do **not** commit upstream MCP repos. `ats-jobs-mcp` ships a ~50k-line company
directory in its **wheel**. Copying that into git made the PR look huge for no
operator benefit.

| Server | How it runs | Pin |
| --- | --- | --- |
| Work at a Startup | `uvx --from workatastartup-mcp==0.1.2` via `scripts/mcp/workatastartup.sh` | PyPI 0.1.2 |
| ATS boards | `uvx --from ats-jobs-mcp==1.0.0` via `scripts/mcp/ats-jobs.sh` | PyPI 1.0.0 |
| job-scout | clone into gitignored `agent-tools/job-scout-mcp` via `scripts/mcp/job-scout.sh` | SHA in `PINNED.txt` |

Warm cache (cloud-agent `install` already does this):

```bash
bash scripts/setup_vendor_mcps.sh
```

Hosted MCPs: [`mcp/hosted/`](../../mcp/hosted/) and [`mcp/SETUP.md`](../../mcp/SETUP.md).

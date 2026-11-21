# Browser e2e stack

The Hub is a Go API plus the React SPA under `web/`. Python Playwright suites
were removed with the Python board.

## Bring the stack up

From repo root:

```bash
bash scripts/e2e_browser.sh
```

That builds `docker-compose.e2e.yml` and waits until
`http://127.0.0.1:18787` answers. Tear down with:

```bash
docker compose -f docker-compose.e2e.yml -p jobos-e2e down -v
```

Operator flows to walk manually are listed in [`FLOWS.md`](FLOWS.md).
Automated coverage lives in `server/` (`go test ./...`) and the `web` CI build.

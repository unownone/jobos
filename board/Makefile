.PHONY: run tokens lint test test-unit test-e2e import bench shots deploy docker

run:
	bash start.sh

deploy:
	bash ../scripts/hub_deploy.sh

docker:
	bash ../scripts/hub_docker.sh

tokens:
	uv run ../scripts/board_gen_tokens.py --dir . --print

lint:
	uv run ruff check . ../scripts

test:
	uv run pytest

test-unit:
	uv run pytest -m unit --strict-markers

test-e2e:
	uv run pytest -m e2e --strict-markers

import:
	uv run ../scripts/board_import_ledger.py --db data/board.db

bench:
	uv run python scripts/benchmark.py

shots:
	bash scripts/capture_readme_shots.sh

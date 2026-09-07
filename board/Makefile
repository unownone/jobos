.PHONY: run tokens test import bench shots

run:
	bash start.sh

tokens:
	uv run ../scripts/board_gen_tokens.py --dir . --print

test:
	uv run pytest

import:
	uv run ../scripts/board_import_ledger.py --db data/board.db

bench:
	uv run python scripts/benchmark.py

shots:
	bash scripts/capture_readme_shots.sh

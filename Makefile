.PHONY: board board-tokens board-test board-bench board-docker

board:
	bash board/start.sh

board-tokens:
	uv run scripts/board_gen_tokens.py --print

board-test:
	$(MAKE) -C board test

board-bench:
	uv run board/scripts/benchmark.py

board-docker:
	bash scripts/hub_docker.sh

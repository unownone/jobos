.PHONY: board board-tokens board-lint board-test board-test-unit board-test-e2e board-bench board-docker deploy

board:
	bash board/start.sh

board-tokens:
	uv run scripts/board_gen_tokens.py --print

board-lint:
	$(MAKE) -C board lint

board-test:
	$(MAKE) -C board test

board-test-unit:
	$(MAKE) -C board test-unit

board-test-e2e:
	$(MAKE) -C board test-e2e

board-bench:
	uv run board/scripts/benchmark.py

board-docker:
	bash scripts/hub_docker.sh

deploy:
	bash scripts/hub_host_deploy.sh

.PHONY: board hub deploy deploy-check docker test

# Local Hub (Go API + SPA from web/dist). Secrets stay under board/.
board hub:
	bash board/start.sh

docker:
	bash scripts/hub_docker.sh

test:
	cd server && go test ./...

deploy:
	bash scripts/hub_host_deploy.sh

deploy-check:
	bash scripts/github_ssh_selftest.sh

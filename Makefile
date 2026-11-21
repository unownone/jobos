.PHONY: hub deploy deploy-check docker docker-plain

hub:
	bash scripts/hub_start.sh

deploy:
	bash scripts/hub_host_deploy.sh

deploy-check:
	bash scripts/github_ssh_selftest.sh

docker:
	bash scripts/hub_docker.sh

docker-plain:
	bash scripts/hub_docker_plain.sh

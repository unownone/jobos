# One container for hosts that take a single Dockerfile (Coolify, Railway, docker run).
# Compose still runs this image as the legacy `hub` service on port 8787.
# Split api+web layout: docker-compose.split.yml
FROM node:22-alpine AS web
WORKDIR /src
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM golang:1.22-bookworm AS build
WORKDIR /src/server
COPY server/go.mod server/go.sum ./
COPY server/third_party ./third_party
RUN go mod download
COPY server/ ./
RUN CGO_ENABLED=0 go build -o /hub ./cmd/hub

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY --from=build /hub /usr/local/bin/hub
COPY --from=web /src/dist /opt/jobos/web
COPY AGENTS.md llms.txt agents.txt /opt/jobos/
COPY docs /opt/jobos/docs
COPY skills /opt/jobos/skills
COPY mcp /opt/jobos/mcp
COPY scripts /opt/jobos/scripts
COPY handoffs /opt/jobos/handoffs
COPY scripts/hub_healthcheck.sh /usr/local/bin/hub-healthcheck
RUN chmod +x /usr/local/bin/hub-healthcheck
# Legacy Coolify/host compose publishes 8787. Railway/Render inject PORT and win.
ENV HUB_REPO_ROOT=/opt/jobos \
    HUB_WEB_ROOT=/opt/jobos/web \
    BOARD_HOST=0.0.0.0 \
    BOARD_PORT=8787
EXPOSE 8787
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=12 \
  CMD ["/usr/local/bin/hub-healthcheck"]
ENTRYPOINT ["/usr/local/bin/hub"]

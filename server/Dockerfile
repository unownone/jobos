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
COPY AGENTS.md llms.txt agents.txt /opt/jobos/
COPY docs /opt/jobos/docs
COPY skills /opt/jobos/skills
COPY mcp /opt/jobos/mcp
COPY scripts /opt/jobos/scripts
COPY handoffs /opt/jobos/handoffs
ENV HUB_ADDR=:8080
ENV HUB_REPO_ROOT=/opt/jobos
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/hub"]

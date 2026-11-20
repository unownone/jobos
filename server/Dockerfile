FROM golang:1.22-bookworm AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /hub ./cmd/hub

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=build /hub /usr/local/bin/hub
ENV HUB_ADDR=:8080
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/hub"]

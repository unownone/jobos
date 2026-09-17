FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/board/.venv/bin:/usr/local/bin:${PATH}" \
    JOBOS_NONINTERACTIVE=1 \
    HUB_REPO_ROOT=/app \
    BOARD_HOST=0.0.0.0 \
    BOARD_PORT=8787 \
    BOARD_DB=/tmp/board.db \
    HUB_PACKS_DIR=/tmp/jobos-packs

COPY board/pyproject.toml board/uv.lock /app/board/
WORKDIR /app/board
RUN uv sync --frozen --no-dev

WORKDIR /app
COPY AGENTS.md skills-lock.json llms.txt agents.txt ./
COPY board ./board
COPY scripts ./scripts
COPY skills ./skills
COPY docs ./docs
COPY mcp ./mcp
COPY handoffs ./handoffs
COPY profiles/candidate.example.yaml ./profiles/candidate.example.yaml
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh /app/board/start.sh

EXPOSE 8787
WORKDIR /app/board
ENTRYPOINT ["/docker-entrypoint.sh"]

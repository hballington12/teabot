# syntax=docker/dockerfile:1
# The instance's image for the quick setup: the locked dependencies, nothing for development.
# Build with `docker compose build`.
FROM ghcr.io/astral-sh/uv:0.9.9-python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml uv.lock ./
# Every package in plugins/ is one of the instance's plugins, so the sync installs them all.
COPY plugins ./plugins
# The site's privacy policy and terms, when the operator writes them.
COPY pages ./pages
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages

RUN useradd --system --no-create-home teabot
USER teabot
CMD ["teabot", "run", "--env-file", "/app/teabot.env"]

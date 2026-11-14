# syntax=docker/dockerfile:1
# The instance's image for the quick setup (D43): the locked dependencies, nothing for development.
# Build with `docker compose build`. While teabot comes from a private GitHub repository, the build reads it
# over SSH: run `ssh-add` first, and Compose forwards your agent.
FROM ghcr.io/astral-sh/uv:0.9.9-python3.12-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml uv.lock ./
# Every package in plugins/ is one of the instance's plugins, so the sync installs them all (D44).
COPY plugins ./plugins
RUN --mount=type=ssh --mount=type=cache,target=/root/.cache/uv \
    mkdir -p -m 0700 /root/.ssh \
    && ssh-keyscan -t ed25519 github.com >> /root/.ssh/known_hosts 2>/dev/null \
    && uv sync --frozen --no-dev --all-packages

RUN useradd --system --no-create-home teabot
USER teabot
CMD ["teabot", "run", "--env-file", "/app/teabot.env"]

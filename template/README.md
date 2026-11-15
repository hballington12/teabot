# A teabot instance

This folder is your own teabot: which plugins it runs, your own plugins, and how it is deployed. To set it up, run `./setup.sh`, following the quick start at https://teabot-dev.github.io/teabot/host/

## What each file is for

- `setup.sh`: sets up and starts the instance with Docker Compose. Safe to run again.
- `compose.yaml`: the bot and Postgres on one machine, and a `uv` service for changing plugins (`docker compose run --rm uv add teabot-foo`).
- `Dockerfile`: the bot's image, with the locked dependencies.
- `pyproject.toml`: the plugins this instance runs. `uv.lock` pins their exact versions; commit it.
- `teabot.env.example`: every setting, explained. `setup.sh` copies it to `teabot.env`, which never goes into git.
- `.env`: the database password and your user and group ids, for Compose. Written by `setup.sh`; never goes into git.
- `plugins/`: plugins you write for this instance, made with `uv run teabot new-plugin <id>`.
- `deploy/bare-metal/`: the careful setup on a dedicated Ubuntu server, with HTTPS and continuous backups. See https://teabot-dev.github.io/teabot/host/bare-metal/

## teabot's own development

teabot's repository uses this Compose file's Postgres for its tests: `docker compose -f template/compose.yaml up -d postgres`. The owner password defaults to `teabot` and the port to `55432`, and `TEABOT_DB_OWNER_PASSWORD` and `TEABOT_DB_PORT` override them.

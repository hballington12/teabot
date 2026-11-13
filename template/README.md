# A teapot instance

The starting point for running your own teapot (D35, D42, D43). Copy this directory into a new repository: it becomes your instance. It holds:
- which plugins the instance runs, in `pyproject.toml`, pinned by `uv.lock`
- your own plugins, in `plugins/`
- how it is deployed, in `compose.yaml` and `deploy/bare-metal/`

teapot itself stays in its own repository, and your instance depends on it.

## The Discord application

1. Create an application at https://discord.com/developers/applications. Use a separate one for testing, so experiments never reach a live server (D38).
2. On the Bot tab:
    - Turn on the **Server Members Intent**; joins, leaves and member lookups need it.
    - Leave **Message Content** off unless a plugin needs message text.
    - Turn **Public Bot** off if only you should invite it.
3. Invite the bot with the `bot` and `applications.commands` scopes. teapot's commands then appear: `/plugins`, `/audit`, `/tokens`, `/admin`, and each enabled plugin's group.
4. A bot must be verified by Discord before it can join more than 100 servers (D39).

## The instance

1. Edit the `dependencies` in `pyproject.toml` to choose plugins, then run `uv lock`.
    - While teapot comes from a private GitHub repository, `uv lock` reads it over SSH with your own key.
    - Commit `uv.lock`. It is the pin, and an upgrade is `uv lock --upgrade-package teapot` followed by a deploy.
2. Copy `teapot.env.example` to `teapot.env`. It never goes into git, as `.gitignore` makes sure.

## Quick setup: Docker Compose

For a working bot in minutes, on one machine.
1. Set `TEAPOT_DISCORD_TOKEN` and `TEAPOT_DB_OWNER_PASSWORD` in `teapot.env`. Export the same owner password as `TEAPOT_DB_OWNER_PASSWORD` for Compose.
2. `ssh-add`, so the image build can read teapot from GitHub.
3. `docker compose build`.
4. `docker compose up -d --wait postgres`.
5. `docker compose run --rm bot teapot init`. It creates the database roles and writes their passwords into `teapot.env`.
6. `docker compose up -d`, then check `curl -s http://127.0.0.1:8780/healthz`.

How it runs:
- The bot runs as your user (`TEAPOT_UID`, `TEAPOT_GID`, 1000 by default), because `teapot.env` holds secrets and is kept at mode 0600.
- MCP and the service API listen on `127.0.0.1:8780`. Put a reverse proxy with HTTPS in front before anyone outside reaches them, and set `TEAPOT_PUBLIC_URL`.

## Careful setup: a bare-metal host

The Tea clan's droplet runs this way (D37), on Ubuntu 24.04:
- Postgres on its Unix socket only
- Caddy for HTTPS, forwarding only `/mcp` and `/api`
- a hardened systemd unit
- pgBackRest streaming WAL to object storage, so a lost host costs about a minute of data

1. Point a DNS record for your hostname at the host.
2. Copy the instance onto the host and run the setup as root:
    ```
    rsync -a --exclude .git --exclude .venv --exclude teapot.env ./ root@host:/root/teapot-setup/
    ssh root@host /root/teapot-setup/deploy/bare-metal/setup-host.sh teapot.example.org git@github.com:you/teapot-you.git
    ```
    The first run stops and prints two deploy keys: one for your instance repository and one for teapot's. Add each to its repository on GitHub as a read-only deploy key, then run it again. It then:
    - installs Postgres 16, pgBackRest, git and uv
    - clones the instance into `/opt/teapot`
    - creates the database and runs `teapot init`
    - adds the Caddy site, then validates and reloads Caddy
    - installs the service
3. `ssh -t root@host /opt/teapot/deploy/bare-metal/set-discord-token.sh` asks for the bot token and starts the bot.
4. `ssh -t root@host /opt/teapot/deploy/bare-metal/setup-backups.sh <bucket> <region>` asks for the bucket's access key and starts continuous backups. It also generates the encryption passphrase. Copy it somewhere safe, because without it no backup can be restored.
5. Later deploys: `deploy/bare-metal/deploy.sh root@host` pulls `main`, syncs, restarts and waits for `/healthz`.

Files:
- `deploy/bare-metal/lib.sh` holds what the scripts share.
- The secrets live on the host only: `/etc/teapot/teapot.env` and `/etc/pgbackrest/conf.d/secrets.conf`.
- `/healthz` answers on the host's localhost only.

## teapot's own development

teapot's repository uses this Compose file's Postgres for its tests: `docker compose -f template/compose.yaml up -d postgres`. The owner password defaults to `teapot` and the port to `55432`, and `TEAPOT_DB_OWNER_PASSWORD` and `TEAPOT_DB_PORT` override them.

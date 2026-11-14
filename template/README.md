# A teabot instance

The starting point for running your own teabot (D35, D42, D43). Copy this directory into a new repository: it becomes your instance. It holds:
- which plugins the instance runs, in `pyproject.toml`, pinned by `uv.lock`
- your own plugins, in `plugins/`
- how it is deployed, in `compose.yaml` and `deploy/bare-metal/`

teabot itself stays in its own repository, and your instance depends on it. For a walkthrough from nothing to a running bot with a plugin of your own, follow `docs/self-hosting.md` in the teabot repository. This README is the reference for the instance's files.

## The Discord application

1. Create an application at https://discord.com/developers/applications. Use a separate one for testing, so experiments never reach a live server (D38).
2. On the Bot tab:
    - Turn on the **Server Members Intent**; joins, leaves and member lookups need it.
    - Leave **Message Content** off unless a plugin needs message text.
    - Turn **Public Bot** off if only you should invite it.
3. Invite the bot with the `bot` and `applications.commands` scopes; `teabot init` prints the link. teabot's commands then appear: `/plugins`, `/audit`, `/tokens`, `/admin`, and each enabled plugin's group.
4. A bot must be verified by Discord before it can join more than 100 servers (D39).

## The instance

1. Edit the `dependencies` in `pyproject.toml` to choose plugins, then run `uv lock`.
    - While teabot comes from a private GitHub repository, `uv lock` reads it over SSH with your own key.
    - Commit `uv.lock`. It is the pin, and an upgrade is `uv lock --upgrade-package teabot` followed by a deploy.
2. Copy `teabot.env.example` to `teabot.env`. It never goes into git, as `.gitignore` makes sure.

## Quick setup: Docker Compose

For a working bot in minutes, on one machine.
1. Set `TEABOT_DISCORD_TOKEN` in `teabot.env`.
    - Then write `.env` for Compose, with a generated owner password and your user and group ids:
      ```
      printf 'TEABOT_DB_OWNER_PASSWORD=%s\nTEABOT_UID=%s\nTEABOT_GID=%s\n' "$(openssl rand -hex 24)" "$(id -u)" "$(id -g)" > .env
      ```
    - Compose reads `.env` on every command and passes the password to Postgres and the bot, so `teabot.env` leaves it blank.
2. `ssh-add`, so the image build can read teabot from GitHub.
3. `docker compose build`.
4. `docker compose up -d --wait postgres`.
5. `docker compose run --rm bot teabot init`. It creates the database roles, writes their passwords into `teabot.env`, and prints the invite link.
6. `docker compose up -d`, then check `curl -s http://127.0.0.1:8780/healthz`.

How it runs:
- The bot runs as your user (`TEABOT_UID`, `TEABOT_GID`, 1000 by default), because `teabot.env` holds secrets and is kept at mode 0600.
- MCP and the service API listen on `127.0.0.1:8780`. Put a reverse proxy with HTTPS in front before anyone outside reaches them, and set `TEABOT_PUBLIC_URL`.

## Careful setup: a bare-metal host

The Tea clan's droplet runs this way (D37), on Ubuntu 24.04:
- Postgres on its Unix socket only
- Caddy for HTTPS, forwarding only `/mcp` and `/api`
- a hardened systemd unit
- pgBackRest streaming WAL to object storage, so a lost host costs about a minute of data

1. Point a DNS record for your hostname at the host.
2. Copy the instance onto the host and run the setup as root:
    ```
    rsync -a --exclude .git --exclude .venv --exclude teabot.env ./ root@host:/root/teabot-setup/
    ssh root@host /root/teabot-setup/deploy/bare-metal/setup-host.sh teabot.example.org git@github.com:you/teabot-you.git
    ```
    The first run stops and prints two deploy keys: one for your instance repository and one for teabot's. Add each to its repository on GitHub as a read-only deploy key, then run it again. It then:
    - installs Postgres 16, pgBackRest, git and uv
    - clones the instance into `/opt/teabot`
    - creates the database and runs `teabot init`
    - adds the Caddy site, then validates and reloads Caddy
    - installs the service
3. `ssh -t root@host /opt/teabot/deploy/bare-metal/set-discord-token.sh` asks for the bot token and starts the bot.
4. `ssh -t root@host /opt/teabot/deploy/bare-metal/setup-backups.sh <bucket> <region>` asks for the bucket's access key and starts continuous backups. It also generates the encryption passphrase. Copy it somewhere safe, because without it no backup can be restored.
5. Later deploys: `deploy/bare-metal/deploy.sh root@host` pulls `main`, syncs, restarts and waits for `/healthz`.
6. The restore drill: `deploy/bare-metal/restore-drill.sh root@host`, from a machine with Docker, restores the latest backup into a scratch container and checks it against the host. It also checks a marker written just before, which proves the archived WAL replays. Run it after setup, and again now and then.

Files:
- `deploy/bare-metal/lib.sh` holds what the scripts share.
- The secrets live on the host only: `/etc/teabot/teabot.env` and `/etc/pgbackrest/conf.d/secrets.conf`.
- `/healthz` answers on the host's localhost only.

## teabot's own development

teabot's repository uses this Compose file's Postgres for its tests: `docker compose -f template/compose.yaml up -d postgres`. The owner password defaults to `teabot` and the port to `55432`, and `TEABOT_DB_OWNER_PASSWORD` and `TEABOT_DB_PORT` override them.

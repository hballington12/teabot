# Run it in production

At the end of this page, your Docker Compose instance is ready for a live server: reachable over HTTPS, watched, backed up, and easy to upgrade.

The [quick start](index.md) is enough to try teabot. For a dedicated server with continuous backups, see [Bare-metal host](bare-metal.md) instead.

## Keep a second bot for testing

Make a second Discord application, and a second instance from the template, for experiments. A test then never reaches your live server.

Never invite two teabot instances to one server. Both would answer its commands.

## HTTPS

AI assistants and your own services reach teabot over HTTP, on `127.0.0.1:8780`. That works only on the same machine. To reach it from anywhere else:

1. Put a reverse proxy with HTTPS in front of it.
2. Forward only `/mcp` and `/api`. Keep `/healthz` on this machine.
3. Keep the original `Host` header, which teabot checks.
4. Set the public address in `teabot.env`, then restart the bot:

    ```ini title="teabot.env"
    TEABOT_PUBLIC_URL=https://teabot.example.org
    ```

    ```bash
    docker compose restart bot
    ```

`/tokens create` then gives AI assistants this address. With [Caddy](https://caddyserver.com/), the template's `deploy/bare-metal/teabot.caddy` does steps 1 to 3:

```text title="deploy/bare-metal/teabot.caddy"
--8<-- "template/deploy/bare-metal/teabot.caddy"
```

## Watch the health check

```bash
curl -s http://127.0.0.1:8780/healthz
```

It answers `"ok":true` while the bot is connected to Discord and its database, with each plugin's status, the queue's backlog and the version:

```json
{"ok":true,"version":"1.2.0","database":true,"queue_backlog":0,"plugins":{"announcements":"loaded","giveaways":"loaded"}}
```

Point your monitoring at it. Compose restarts the bot if it stops.

## Upgrade

1. Read the [release notes](changelog.md) for every release since yours. A release's **For operators** part lists any step you must take by hand. Your version is:

    ```bash
    docker compose run --rm bot teabot --version
    ```

2. Upgrade and rebuild:

    ```bash
    docker compose run --rm uv lock --upgrade-package teabot
    docker compose up -d --build
    ```

    The bot updates its database when it starts.

3. Check that `/healthz` answers `"ok":true` with the new version, then commit `uv.lock`.

A plugin upgrades the same way, by its package name, such as `--upgrade-package teabot-example`. Read its changes first, since it runs inside your bot.

## Back up

All of teabot's data is in its Postgres database: settings, plugin data, tokens and the audit log. Save a copy, with the database roles that own it, and keep it off this machine:

```bash
docker compose exec -T postgres pg_dumpall -U teabot_owner > teabot.sql
```

Run it on a timer, such as a daily cron job. Keep `.env` and `teabot.env` safe as well, since the copy only opens with their passwords.

To restore on a new machine, download the template, put your `.env` and `teabot.env` in its folder, then:

```bash
docker compose up -d --wait postgres
docker compose exec -T postgres psql -U teabot_owner -d postgres < teabot.sql
./setup.sh
```

The restore reports that the role `teabot_owner` and the database `teabot` already exist. That is expected: Postgres made them when it started, and the restore fills them in.

## Growing past 100 servers

Discord must verify a bot before it can join more than 100 servers. Apply in the developer portal before you get close.

**Next:** [Bare-metal host](bare-metal.md), or [Release notes](changelog.md).

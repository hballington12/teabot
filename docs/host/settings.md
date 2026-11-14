# Settings

teabot reads its settings from `teabot.env`, in your instance's folder. After a change, restart the bot:

```bash
docker compose restart bot
```

## The ones people change

| Setting | What it does |
|---|---|
| `TEABOT_DISCORD_TOKEN` | The bot's token. `setup.sh` writes it. |
| `TEABOT_PUBLIC_URL` | Your bot's public HTTPS address, so AI assistants on other machines can connect. See [HTTPS](production.md#https). |
| `TEABOT_DISABLED_PLUGINS` | Plugins turned off in every server. See [Adding plugins](adding-plugins.md#turn-a-plugin-off-everywhere). |
| `TEABOT_GUILD_RETENTION_DAYS` | How long a server's data is kept after the bot leaves it. |

## Every setting

This is the template's `teabot.env.example`, which `setup.sh` copies to `teabot.env`:

```ini title="teabot.env"
--8<-- "template/teabot.env.example"
```

## The `.env` file

Docker Compose reads `.env`, which `setup.sh` writes. It is separate from `teabot.env`.

```ini title=".env"
TEABOT_DB_OWNER_PASSWORD=...   # the database password; Postgres keeps the one it first started with
TEABOT_UID=1000                # the user and group the bot runs as, who must own teabot.env
TEABOT_GID=1000
```

Two more are optional: `TEABOT_DB_PORT` (default `55432`) and `TEABOT_HTTP_PORT` (default `8780`), the ports Postgres and the bot listen on, on this machine only.

**Next:** [Adding plugins](adding-plugins.md).

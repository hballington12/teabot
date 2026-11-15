# Settings

teabot reads its settings from `teabot.env`, in your instance's folder. After a change, recreate the bot's container, so it reads the file again:

```bash
docker compose up -d --force-recreate bot
```

On a [bare-metal host](bare-metal.md), the file is `/etc/teabot/teabot.env`, and the restart is `systemctl restart teabot`.

## The ones people change

| Setting | What it does |
|---|---|
| `TEABOT_DISCORD_TOKEN` | The bot's token. `setup.sh` writes it. |
| `TEABOT_PUBLIC_URL` | Your bot's public HTTPS address, so AI assistants on other machines can connect. See [HTTPS](production.md#https). |
| `TEABOT_DISABLED_PLUGINS` | Plugins turned off in every server. See [Adding plugins](adding-plugins.md#turn-a-plugin-off-everywhere). |
| `TEABOT_GUILD_RETENTION_DAYS` | How long a server's data is kept after the bot leaves it. |
| `TEABOT_MESSAGE_CONTENT` | `true` lets plugins read what members write. Turn on **Message Content Intent** under **Bot** in the Discord developer portal first. A bot in more than 100 servers needs Discord's approval for it. |

A plugin may need settings of its own, such as an API key. They are named `TEABOT_PLUGIN_<ID>_<NAME>`, such as `TEABOT_PLUGIN_WOM_API_KEY`, and go in `teabot.env` too. The plugin's README lists them. Restart teabot after changing one.

## Every setting

This is the template's `teabot.env.example`, which `setup.sh` copies to `teabot.env`:

```ini title="teabot.env"
--8<-- "template/teabot.env.example"
```

## The `.env` file

Docker Compose reads `.env`, which `setup.sh` writes. It is separate from `teabot.env`:

```ini title=".env"
TEABOT_DB_OWNER_PASSWORD=...   # the database password; Postgres keeps the one it first started with
TEABOT_UID=1000                # the user and group the bot runs as, who must own teabot.env
TEABOT_GID=1000
```

To use other ports on this machine, add `TEABOT_HTTP_PORT` (default `8780`) or `TEABOT_DB_PORT` (default `55432`) to `.env`, not to `teabot.env`, then run `docker compose up -d`.

The bot may use up to 1 GB of memory, and is restarted if it goes past, so a leak cannot starve Postgres. Set `TEABOT_MEMORY_LIMIT` in `.env`, such as `TEABOT_MEMORY_LIMIT=2g`, to change it. On a bare-metal host, it is `MemoryMax=` in `teabot.service`.

**Next:** [Adding plugins](adding-plugins.md).

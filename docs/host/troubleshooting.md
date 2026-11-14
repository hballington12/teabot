# Troubleshooting

Each problem below starts with what you see. Look at the bot's log first, since it names most problems:

```bash
docker compose logs bot
```

On a [bare-metal host](bare-metal.md), the log is `journalctl -u teabot`.

## `setup.sh` stops with "would lock teabot out of its database"

The database already exists, but `.env`, which holds its password, is missing. Postgres keeps the password it was first started with.

- If you have the old `.env`, put it back and run `./setup.sh` again.
- On a new install with nothing to keep, delete the database, then run `./setup.sh` again:

    ```bash
    docker compose down -v
    ```

    !!! warning

        `down -v` deletes the database. Never run it on an install with data you want.

## `/healthz` does not say `"ok":true`

- **`PrivilegedIntentsRequired` in the log.** Turn on **Server Members Intent** on the **Bot** tab of the developer portal, then restart:

    ```bash
    docker compose restart bot
    ```

- **`LoginFailure` or `Improper token` in the log.** The token in `teabot.env` is wrong. Reset it in the developer portal, put the new one after `TEABOT_DISCORD_TOKEN=` in `teabot.env`, and restart.

## `password authentication failed for user "teabot_owner"`

The database is older than your `.env`, so it expects a different password. This is the case above: put the old `.env` back, or on a new install delete the database with `docker compose down -v`.

## `Permission denied` reading `/app/teabot.env`

`TEABOT_UID` and `TEABOT_GID` in `.env` must be the ids of the user who owns `teabot.env`. Compare:

```bash
ls -ln teabot.env
id -u; id -g
```

## A plugin does not load

The log names each plugin that failed, with the reason. So does:

```bash
docker compose run --rm bot teabot plugins list
```

- A plugin you added or changed needs `docker compose up -d --build`.
- Two plugins with the same id both fail to load. Remove one.

## Commands do not appear in Discord

- A plugin's commands appear in a server only after [`/plugins enable`](../use/plugins.md).
- A member sees only the commands they can use. See [Who can use what](../use/permissions.md).
- New commands can take a minute. Reload Discord with ++ctrl+r++, or ++cmd+r++ on macOS.

For problems inside a server, such as a command that refuses, see [Using teabot's troubleshooting](../use/troubleshooting.md).

# Troubleshooting

Each problem below starts with what you see. Look at the bot's log first, since it names most problems:

```bash
docker compose logs bot
```

On a [bare-metal host](bare-metal.md), the log is `journalctl -u teabot`.

## `setup.sh` says "cannot reach Docker"

Docker is not running, or on Linux your user may not use it. Start Docker, or add yourself to the `docker` group, then log out and in again:

```bash
sudo usermod -aG docker $USER
```

## "did not become healthy within 90 seconds"

`setup.sh` printed the end of the bot's log above this message.

- **`LoginFailure` or `Improper token`.** The token is wrong. Reset it in the developer portal, put the new one after `TEABOT_DISCORD_TOKEN=` in `teabot.env`, and run `./setup.sh` again.
- **`PrivilegedIntentsRequired`.** Turn on **Server Members Intent** on the **Bot** tab of the developer portal, then run `./setup.sh` again.

## "A new password would lock teabot out of its database"

Or, from the bot's log: `password authentication failed for user "teabot_owner"`.

The database already exists, but `.env`, which holds its password, is missing or newer than it. Postgres keeps the password it was first started with.

- If you have the old `.env`, put it back and run `./setup.sh` again.
- On a new install with nothing to keep, delete the database, then run `./setup.sh` again:

    ```bash
    docker compose down -v
    ```

    !!! warning

        `down -v` deletes the database of every teabot on this machine. Never run it on an install with data you want.

## `/healthz` stops saying `"ok":true`

The log says why. The two usual causes are the same as at setup: a token that was reset (put the new one in `teabot.env`), or the **Server Members Intent** turned off. After fixing either, recreate the bot:

```bash
docker compose up -d --force-recreate bot
```

## `Permission denied` reading `/app/teabot.env`

`TEABOT_UID` and `TEABOT_GID` in `.env` must be the ids of the user who owns `teabot.env`. Compare:

```bash
ls -ln teabot.env
id -u; id -g
```

Put your ids in `.env`, then run `docker compose up -d`.

## A setting change did nothing

The bot reads `teabot.env` when its container starts. Recreate it, which `restart` does not do:

```bash
docker compose up -d --force-recreate bot
```

## A plugin does not load

`/healthz` shows each plugin's state, such as `failed` or `duplicate_id`, and the log names the error:

```bash
curl -s http://127.0.0.1:8780/healthz
docker compose logs bot | grep -i plugin
```

- A plugin you added or changed needs `docker compose up -d --build`.
- `duplicate_id` means two plugins have the same id, so neither loads. Remove one.

## Commands do not appear in Discord

- A plugin's commands appear in a server only after [`/plugins enable`](../use/plugins.md).
- A member sees only the commands they can use. See [Who can use what](../use/permissions.md).
- New commands can take a minute. Reload Discord with ++ctrl+r++, or ++cmd+r++ on macOS.

For problems inside a server, such as a command that refuses, see [Using teabot's troubleshooting](../use/troubleshooting.md).

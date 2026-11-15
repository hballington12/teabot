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

## The log says `event loop blocked`

A plugin held teabot for more than a second, and the log line names it, with the file and line. Past thirty seconds teabot stops, logs every thread's traceback, and Compose or systemd starts it again. A job that does this on every attempt is failed, so it does not stop teabot over and over. If one plugin keeps doing it, block it with `TEABOT_DISABLED_PLUGINS` (see [Turn a plugin off everywhere](adding-plugins.md#turn-a-plugin-off-everywhere)) and tell its author.

## A plugin you installed may be harmful

A plugin runs inside the bot, with everything the bot can reach: its Discord token and its database passwords. If you think one has misused them:

1. Remove the plugin and deploy, as in [Remove a plugin](adding-plugins.md#remove-a-plugin). Blocking it is not enough, since its code may already have taken the secrets.
2. Reset the bot's token in the Discord developer portal, under **Bot**, then **Reset Token**. Put the new one in `teabot.env`.
3. Give the database new passwords, and restart the bot:

    ```bash
    docker compose run --rm bot teabot init --rotate
    docker compose up -d --force-recreate bot
    ```

4. Give the owner role a new password too. Set it in Postgres, put the same value in `.env` as `TEABOT_DB_OWNER_PASSWORD`, and recreate both services:

    ```bash
    docker compose exec postgres psql -U teabot_owner -d teabot -c "ALTER ROLE teabot_owner PASSWORD 'the-new-password'"
    docker compose up -d --force-recreate
    ```

5. If it came from the [plugin hub](https://teabot-dev.github.io/plugin-hub/), report it there, so it can be delisted for everyone.

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

# Self-hosting teabot

This guide takes you from nothing to your own teabot bot in a Discord server, running a plugin you wrote. It uses the quick setup: Docker Compose on one machine. Plan on half an hour. Decision numbers such as (D26) point at [design.md](design.md).

## What you need

- A Linux or macOS machine with Docker and its Compose plugin. `docker compose version` should print v2 or later.
- `curl`, `openssl` and `git`.
- [uv](https://docs.astral.sh/uv/getting-started/installation/), for writing plugins in step 6.
- A Discord server where you have Manage Server. A test server of your own is best for a first run.

## 1. Get the template

```
mkdir my-teabot && cd my-teabot
curl -sL https://github.com/hballington12/teabot/releases/latest/download/teabot-template.tar.gz | tar xz
git init
```

- This directory is now your instance (D42). `pyproject.toml` lists the plugins it runs, `uv.lock` pins their versions, `compose.yaml` runs it, and `plugins/` holds the plugins you write.
- Keeping it in git makes upgrades and moves easy. Its `.gitignore` keeps the secret files out.

## 2. Create the Discord application

1. Open the [developer portal](https://discord.com/developers/applications) and choose **New Application**.
2. On the **Bot** tab:
    - Choose **Reset Token** and copy the token. You need it in step 3. Anyone who has it controls your bot, so keep it like a password.
    - Turn on the **Server Members Intent** and save. teabot needs it for joins, leaves and member lookups.
    - Leave the **Message Content Intent** off. No plugin of teabot's needs message text.
    - Turn **Public Bot** off, unless other people should be able to invite your bot.

Wait with the invite: `teabot init` prints the link in step 4.

## 3. Configure it

```
cp teabot.env.example teabot.env
chmod 600 teabot.env
printf 'TEABOT_DB_OWNER_PASSWORD=%s\nTEABOT_UID=%s\nTEABOT_GID=%s\n' "$(openssl rand -hex 24)" "$(id -u)" "$(id -g)" > .env
```

Then open `teabot.env` and paste the token after `TEABOT_DISCORD_TOKEN=`.

- `teabot.env` holds the bot's settings and secrets. Its comments explain each one, and `teabot init` fills in the database passwords.
- `.env` is for Compose. It holds the database owner's password, which Compose gives to Postgres and the bot, and your user and group ids, so the bot can read `teabot.env`.

## 4. Start it

```
docker compose build
docker compose up -d --wait postgres
docker compose run --rm bot teabot init
docker compose up -d
curl -s http://127.0.0.1:8780/healthz
```

- `teabot init` creates the database roles, then prints the Discord settings to check and the invite link. Copy the link.
- `/healthz` answers `"ok":true` once the bot has connected to Discord, a few seconds after it starts. If it does not, see [Troubleshooting](#troubleshooting).

## 5. Invite it and try it

1. Open the invite link, choose your server and authorize.
2. In **Server Settings**, then **Roles**, drag the bot's role below your own role and those of your senior staff (D26). The bot has Administrator, and the role order is what stops it from editing the roles above its own.
3. In any channel:
    - `/plugins enable plugin:announcements` turns on the announcements plugin for this server.
    - `/audit channel` chooses where teabot posts each change made through it. Pick a staff channel.
    - `/announcements post` asks for the text in a form and posts it as an embed. The audit channel shows who posted it.

New commands can take a moment to appear. If they do not, reload Discord with Ctrl+R (Cmd+R on macOS).

## 6. Write a plugin

```
uv run teabot new-plugin raffles
uv lock
uv run --env-file .env --package teabot-raffles pytest plugins/raffles
```

- `new-plugin` writes `plugins/raffles/`: the package with one example action, its first migration, a README, tests and a snapshot test.
- The tests run against the Compose Postgres, in databases they create and drop themselves. Run them on your own machine and never on one whose Postgres holds live data.
- The example is `/raffles hello`. Replace it with your own actions in `plugins/raffles/src/teabot_raffles/__init__.py`. The [tutorial](tutorial.md) builds a complete plugin step by step, and [Writing a teabot plugin](plugin-authoring.md) is the reference for actions, inputs, jobs, config, plans and tests.

Then build it into the bot and turn it on:

```
docker compose build
docker compose up -d
```

In Discord, `/plugins enable plugin:raffles`, then `/raffles hello`.

Every package in `plugins/` is one of the instance's plugins, so there is nothing else to register. It is your plugin on your instance, and nobody needs to approve it (D44).

## 7. Connect an LLM client

This step is optional. teabot's actions are also MCP tools, so an LLM client such as Claude Code can use them.

1. In Discord, `/tokens create label:claude`. The token is shown to you once.
2. On the machine running teabot:
    ```
    claude mcp add --transport http teabot http://127.0.0.1:8780/mcp --header "Authorization: Bearer <token>"
    ```
3. In Claude Code, `/mcp` should show `teabot` as connected.

- Every tool acts in that one server as you, with the permissions you have there at the time of each call (D16).
- `/tokens create` can narrow a token to a lower risk or to named actions. `/tokens revoke` ends one.
- From another machine, put teabot behind HTTPS first (step 8).

## 8. Run it for real

- **HTTPS.** MCP and the service API listen on `127.0.0.1:8780`. To reach them from elsewhere, put a reverse proxy with HTTPS in front that forwards only `/mcp` and `/api`, and set `TEABOT_PUBLIC_URL` in `teabot.env` to its address. `deploy/bare-metal/teabot.caddy` is an example for Caddy.
- **Backups.** The data lives in the `teabot-pgdata` volume. Save a dump on a timer with `docker compose exec -T postgres pg_dump -U teabot_owner teabot > teabot.sql`, and keep copies off the machine. For continuous backups, the template's README describes the careful setup with pgBackRest.
- **Upgrades.** Read the changelog, then run `uv lock --upgrade-package teabot`, `docker compose build` and `docker compose up -d`. Migrations run when the bot starts.
- **Testing.** Make a second Discord application and a second instance for experiments, so they never reach your live server (D38).
- **One teabot per server.** Two instances in one server would both answer its commands.
- **Growing.** Discord must verify a bot before it can join more than 100 servers (D39).

## Troubleshooting

`docker compose logs bot` shows what the bot says. Look there first.

- **`/healthz` does not answer `"ok":true`.**
    - `PrivilegedIntentsRequired` in the log: turn on the Server Members Intent (step 2), then `docker compose restart bot`.
    - `LoginFailure` or `Improper token` in the log: the token in `teabot.env` is wrong. Reset it in the portal, paste it again, then `docker compose restart bot`.
- **`password authentication failed for user "teabot_owner"`.** Postgres keeps the password it was first started with, so its volume predates your `.env`. On a new install with nothing to keep, `docker compose down -v` deletes the volume. Then start again from step 4.
- **`Permission denied` reading `/app/teabot.env`.** `TEABOT_UID` and `TEABOT_GID` in `.env` must be the ids of the user who owns `teabot.env`.
- **A plugin's commands do not appear.** A plugin's commands appear in a server only after `/plugins enable`. A plugin you wrote also needs `docker compose build` and `docker compose up -d` after each change, and `docker compose logs bot` names any plugin that failed to load.
- **A command says you lack permissions.** Each action needs the Discord permissions it names, such as Manage Server, checked on every call.

# Adding plugins

At the end of this page, you can install, remove and block plugins on your instance.

A plugin is installed on your instance by you, the operator, and then turned on in each server that wants it by that server's admins, with [`/plugins enable`](../use/plugins.md). Installing decides which code your bot runs. Turning on decides where it is used.

## The plugins that come with teabot

[Announcements](../use/plugins/announcements.md) and [roles](../use/plugins/roles.md) ship inside teabot. They are installed already, and off in every server until an admin turns them on.

## Install a plugin from the hub

The [plugin hub](../hub/index.md) lists the plugins teabot's maintainers have reviewed, each with what it does and every server outside Discord it contacts. Find one there, or from your instance's folder:

```bash
uv run teabot hub search
uv run teabot hub show wom
```

Install it, then rebuild the bot:

```bash
uv run teabot hub add wom
docker compose up -d --build
```

`teabot hub add` adds the newest reviewed version of the plugin that runs on your teabot, pinned to the exact commit that was reviewed, to `pyproject.toml` and `uv.lock`. Commit both files. Without uv on the machine, copy the plugin's install line from the hub's page instead: it does the same through Compose.

To see which of your hub plugins have a newer reviewed version:

```bash
uv run teabot hub outdated
```

It prints `uv run teabot hub add <id>` for each, which moves it to the newer commit. It also says when the hub no longer lists a plugin you have.

## Offer the whole hub to your servers

An instance that serves many servers can install every plugin the hub lists, and let each server's admins turn on the ones they want:

```bash
uv run teabot hub sync
docker compose up -d --build
```

`teabot hub sync` installs each listed plugin at the newest reviewed version your teabot runs, and moves the ones you have to newer reviewed versions. A plugin whose every reviewed version needs a newer teabot is left out, and named. `--skip <id>` leaves one out on purpose. Nothing is turned on: each server still chooses with `/plugins enable`.

To keep up with the hub, run `uv run teabot hub sync --check` on a schedule. It changes nothing, and exits 1 when there is something to sync.

## Install any other plugin

Plugins are Python packages, usually named `teabot-` and the plugin's name. Add one by its package name, then rebuild the bot. Here `teabot-raffles` stands for the plugin you want:

```bash
docker compose run --rm uv add teabot-raffles
docker compose up -d --build
```

The first command adds the plugin to `pyproject.toml`, and pins its exact version in `uv.lock`. Commit both files.

A plugin that is not on PyPI can be added from git, at a tag you have read:

```bash
docker compose run --rm uv add "teabot-raffles @ git+https://github.com/someone/teabot-raffles@v1.0.0"
```

!!! warning

    A plugin runs inside your bot. It can do anything the bot can. Before you install one, read its code, and the "External connections" in its README, which lists every server outside Discord it contacts.

Plugins you write yourself live in your instance's `plugins/` folder, and need no install step. See [Your first plugin](../plugins/index.md).

## See what is installed

```bash
docker compose run --rm bot teabot plugins list
```

It lists each plugin that has tables, with its database version, and whether the running bot has it loaded. `/healthz` shows every plugin's state, with the reason when one failed to load. See [Watch the health check](production.md#watch-the-health-check).

## Turn a plugin off everywhere

To stop a plugin in every server without removing it, name it in `teabot.env`:

```ini title="teabot.env"
TEABOT_DISABLED_PLUGINS=giveaways
```

```bash
docker compose up -d --force-recreate bot
```

Its data is kept, so removing the name turns it back on as it was. A blocked plugin is not even imported, so none of its code runs, which makes this the quick fix for a plugin that hangs or crashes the bot. To be rid of a plugin you no longer trust, remove it, as below.

## Remove a plugin

```bash
docker compose run --rm uv remove teabot-raffles
docker compose up -d --build
```

Removing a plugin keeps its data, so installing it again carries on where it left off. To delete its data in every server, remove it first, then purge it by its id, here `raffles`:

```bash
docker compose run --rm bot teabot plugins purge raffles
```

!!! warning

    `purge` deletes the plugin's tables, settings and queued jobs in every server. It cannot be undone. It refuses while the bot still has the plugin loaded.

On a [bare-metal host](bare-metal.md), change `pyproject.toml` and `uv.lock` the same way on your own machine, commit them, and deploy. Run `teabot plugins` there as `sudo -u teabot /opt/teabot/.venv/bin/teabot plugins list --env-file /etc/teabot/teabot.env`.

**Next:** [Run it in production](production.md).

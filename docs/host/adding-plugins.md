# Adding plugins

At the end of this page, you can install, remove and block plugins on your instance.

A plugin is installed on your instance by you, the operator, and then turned on in each server that wants it by that server's admins, with [`/plugins enable`](../use/plugins.md). Installing decides which code your bot runs. Turning on decides where it is used.

## The plugins that come with teabot

[Announcements](../use/plugins/announcements.md) and [giveaways](../use/plugins/giveaways.md) ship inside teabot. They are installed already, and off in every server until an admin turns them on.

## Install a plugin

Plugins are Python packages. Add one by its name on PyPI, then rebuild the bot:

```bash
docker compose run --rm uv add teabot-example
docker compose up -d --build
```

The first command adds the plugin to `pyproject.toml` and pins its exact version in `uv.lock`. Commit both files.

A plugin that is not on PyPI can be added from git, at a tag you have read:

```bash
docker compose run --rm uv add "teabot-example @ git+https://github.com/someone/teabot-example@v1.0.0"
```

!!! warning

    A plugin runs inside your bot. It can do anything the bot can. Before you install one, read its code, and the "External connections" in its README, which lists every server outside Discord it contacts.

Plugins you write yourself live in your instance's `plugins/` folder, and need no install step. See [Your first plugin](../plugins/index.md).

## See what is installed

```bash
docker compose run --rm bot teabot plugins list
```

It lists each plugin with its database version, and whether the running bot has it loaded.

## Turn a plugin off everywhere

To stop a plugin in every server without removing it, name it in `teabot.env`, then restart:

```ini title="teabot.env"
TEABOT_DISABLED_PLUGINS=giveaways
```

```bash
docker compose restart bot
```

Its data is kept, so removing the name turns it back on as it was.

## Remove a plugin

```bash
docker compose run --rm uv remove teabot-example
docker compose up -d --build
```

Removing a plugin keeps its data, so installing it again carries on where it left off. To delete its data in every server, remove it first, then:

```bash
docker compose run --rm bot teabot plugins purge example
```

!!! warning

    `purge` deletes the plugin's tables, settings and queued jobs in every server. It cannot be undone. It refuses while the bot still has the plugin loaded.

**Next:** [Run it in production](production.md).

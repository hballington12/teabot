<div align="center">

<img src="https://raw.githubusercontent.com/hballington12/teabot/main/brand/teabot.png" width="160" alt="teabot" />

<h1>teabot</h1>

<p><b>An open-source, plugin-based Discord bot.</b></p>

<p>
  <a href="https://pypi.org/project/teabot/"><img alt="PyPI" src="https://img.shields.io/pypi/v/teabot?color=d4a72c"></a>
  <a href="https://pypi.org/project/teabot/"><img alt="Python 3.12 and 3.13" src="https://img.shields.io/badge/python-3.12%20%7C%203.13-d4a72c"></a>
  <a href="https://github.com/hballington12/teabot/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/hballington12/teabot/ci.yml?branch=main&label=CI"></a>
  <a href="https://github.com/hballington12/teabot/blob/main/LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-yellow.svg"></a>
  <a href="https://buymeacoffee.com/hballington"><img alt="Support" src="https://img.shields.io/badge/support-buy%20me%20a%20coffee-d4a72c"></a>
</p>

</div>

teabot is a Discord bot you run yourself and extend with plugins. Every action a plugin offers is a slash command for your members, a tool for LLM clients such as Claude Code, and an HTTP route for your own services, all at once. Each call checks the member's current Discord permissions and lands in an audit log.

## Features

- **Plugins, enabled per server.** Each plugin keeps its own tables and config, isolated from the core and from other plugins by Postgres roles.
- **Three front doors, one call path.** Slash commands, an MCP server and a service API all run the same checks, and multi-line input gets a Discord form of its own.
- **Tokens tied to members.** An LLM client acts as the member who made its token, never beyond their permissions, and a token can be narrowed to a lower risk or to named actions.
- **Plan, then apply.** A destructive action shows exactly what it would change and applies only once the member confirms. If the target changed in between, it plans again.
- **A queue in Postgres.** Scheduled jobs and long-running changes survive restarts and report their progress.
- **Built to grow.** Automatic sharding, per-server command sync, and a design made for many servers and large member counts.

## Quick start

You need Docker with Compose, and a Discord application with the Server Members Intent turned on.

```
mkdir my-teabot && cd my-teabot
curl -sL https://github.com/hballington12/teabot/releases/latest/download/teabot-template.tar.gz | tar xz
cp teabot.env.example teabot.env && chmod 600 teabot.env    # then paste your bot token into it
printf 'TEABOT_DB_OWNER_PASSWORD=%s\nTEABOT_UID=%s\nTEABOT_GID=%s\n' "$(openssl rand -hex 24)" "$(id -u)" "$(id -g)" > .env
docker compose build && docker compose up -d --wait postgres
docker compose run --rm bot teabot init    # prints the invite link
docker compose up -d
```

Then invite the bot, and run `/plugins enable plugin:announcements` in your server. The [self-hosting guide](https://github.com/hballington12/teabot/blob/main/docs/self-hosting.md) walks through every step, from creating the Discord application to running it for real.

## Write a plugin

```
uv run teabot new-plugin raffles
```

That writes a package with an example action, its first migration and its tests. An action is a pydantic input, an output, and a function:

```python
class Hello(BaseModel):
    greeting: str = Field(default="hello", max_length=100, description="What to say")


async def hello(ctx: ActionContext, data: Hello) -> Greeted:
    async with ctx.db.transaction() as tx:
        await tx.execute("INSERT INTO greetings (guild_id, member_id, greeting) VALUES ($1, $2, $3)",
                         ctx.guild.id, ctx.actor.user_id, data.greeting)
        times = await tx.fetchval("SELECT count(*) FROM greetings WHERE guild_id = $1 AND member_id = $2",
                                  ctx.guild.id, ctx.actor.user_id)
    return Greeted(times=times)
```

It becomes `/raffles hello` in Discord, the `raffles_hello` tool over MCP, and `POST /api/v1/actions/raffles.hello`. Your plugins need nobody's approval: they live in your instance and run on your bot. [Writing a teabot plugin](https://github.com/hballington12/teabot/blob/main/docs/plugin-authoring.md) covers actions, inputs, jobs, config and plans.

## Plugins

| Plugin | What it does |
|---|---|
| [`teabot-announcements`](https://pypi.org/project/teabot-announcements/) | Posts an announcement to a channel, now or at a set time. |

## Connect an LLM client

Make a token with `/tokens create`, then add the server to Claude Code:

```
claude mcp add --transport http teabot https://your-host/mcp --header "Authorization: Bearer <token>"
```

Every tool acts in that one server as you, with the permissions you have there at the moment of each call.

## Documentation

- [Self-hosting](https://github.com/hballington12/teabot/blob/main/docs/self-hosting.md): from nothing to a running bot with a plugin of your own.
- [Writing a plugin](https://github.com/hballington12/teabot/blob/main/docs/plugin-authoring.md): the SDK, testing, and the review checklist.
- [Design](https://github.com/hballington12/teabot/blob/main/docs/design.md): the numbered decisions behind teabot, with their reasons.
- [Architecture](https://github.com/hballington12/teabot/blob/main/docs/architecture.md): how the pieces fit together, and what comes later.
- [Changelog](https://github.com/hballington12/teabot/blob/main/CHANGELOG.md).

## Contributing

Issues and pull requests are welcome. [CONTRIBUTING.md](https://github.com/hballington12/teabot/blob/main/CONTRIBUTING.md) covers the setup and the checks, and [SECURITY.md](https://github.com/hballington12/teabot/blob/main/SECURITY.md) how to report a vulnerability privately. Everyone taking part follows the [code of conduct](https://github.com/hballington12/teabot/blob/main/CODE_OF_CONDUCT.md).

## Support

teabot is free and MIT-licensed. If it is useful to you, you can [buy me a coffee](https://buymeacoffee.com/hballington).

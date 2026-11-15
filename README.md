<div align="center">

<img src="https://raw.githubusercontent.com/teabot-dev/teabot/main/brand/teabot.png" width="160" alt="Teabot" />

<h1>Teabot</h1>

<p><b>An open-source, plugin-based Discord bot.</b></p>

<p>
  <a href="https://pypi.org/project/teabot/"><img alt="PyPI" src="https://img.shields.io/pypi/v/teabot?color=d4a72c&cacheSeconds=3600"></a>
  <a href="https://pypi.org/project/teabot/"><img alt="Python 3.12 and 3.13" src="https://img.shields.io/badge/python-3.12%20%7C%203.13-d4a72c"></a>
  <a href="https://github.com/teabot-dev/teabot/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/teabot-dev/teabot/ci.yml?branch=main&label=CI"></a>
  <a href="https://github.com/teabot-dev/teabot/blob/main/LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-yellow.svg"></a>
  <a href="https://buymeacoffee.com/hballington"><img alt="Support" src="https://img.shields.io/badge/support-buy%20me%20a%20coffee-d4a72c"></a>
</p>

</div>

<p align="center">Teabot is a scalable, open-source, plugin-based bot for Discord. It works with slash commands, LLMs through MCP, and your own services via HTTP.</p>

## Why Teabot?

- **Easy to use.** Connect it to any MCP client, such as Claude Code, in a few minutes, and let it handle your Discord management the modern way.
- **Freely customisable.** Make Teabot work for you. Pick the plugins your server needs, and leave paywalled bot features behind.
- **Endless possibilities.** The plugin SDK wires your own plugins straight into Teabot, so you skip the boring parts and get straight to making your server what you want it to be.
- **Safe by design.** Set the permissions and Teabot enforces them. You choose who does what, and destructive changes always await confirmation.

## Quick start

1. **Add our bot.** A hosted Teabot is on its way, free for early adopters. Watch this repository to hear when it opens.
2. **Host it yourself.** Follow the [quick start](https://teabot-dev.github.io/teabot/host/): with Docker, you have your own Teabot running in about 15 minutes.

## Plugins

| Plugin | What it does |
|---|---|
| [`announcements`](https://github.com/teabot-dev/teabot/tree/main/src/teabot/plugins/announcements) | Posts an announcement to a channel, now or at a set time. |
| [`roles`](https://github.com/teabot-dev/teabot/tree/main/src/teabot/plugins/roles) | Posts a role picker: a button for each role, which members press to take it. |

These ship with teabot. Turn one on in a server with `/plugins enable plugin:<name>`.

More, such as giveaways, are on the [plugin hub](https://teabot-dev.github.io/plugin-hub/), where teabot's maintainers review each one. To write your own, see [Your first plugin](https://teabot-dev.github.io/teabot/plugins/).

## Documentation

Everything is on the [documentation site](https://teabot-dev.github.io/teabot/):
- [Using Teabot](https://teabot-dev.github.io/teabot/use/): adding it to your server, plugins, permissions and AI assistants.
- [Self-hosting](https://teabot-dev.github.io/teabot/host/): running your own, from nothing to a live bot.
- [Writing plugins](https://teabot-dev.github.io/teabot/plugins/): your first plugin, a tutorial, and the reference.
- [Release notes](https://teabot-dev.github.io/teabot/host/changelog/).

For contributors, the [design decisions and architecture](https://github.com/teabot-dev/teabot/tree/main/design) explain how Teabot is built.

## Contributing

Issues and pull requests are welcome. [CONTRIBUTING.md](https://github.com/teabot-dev/teabot/blob/main/CONTRIBUTING.md) covers the setup and the checks, and [SECURITY.md](https://github.com/teabot-dev/teabot/blob/main/SECURITY.md) how to report a vulnerability privately. Everyone taking part follows the [code of conduct](https://github.com/teabot-dev/teabot/blob/main/CODE_OF_CONDUCT.md).

## Support

Teabot is free and MIT-licensed. If it is useful to you, you can [buy me a coffee](https://buymeacoffee.com/hballington).

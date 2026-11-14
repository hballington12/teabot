# Built-in commands

These commands come with teabot, and work in every server. Plugins add more: see [Announcements](plugins/announcements.md) and [Giveaways](plugins/giveaways.md).

## `/plugins`

| Command | What it does | Needs |
|---|---|---|
| `/plugins list` | Lists the plugins, and whether each is on here. | Manage Server |
| `/plugins enable` | Turns a plugin on here. | Manage Server |
| `/plugins disable` | Turns a plugin off here. Its data is kept. | Manage Server |
| `/plugins config` | Shows a plugin's settings, or changes one. | Manage Server |

See [Turn on plugins](plugins.md).

## `/audit`

| Command | What it does | Needs |
|---|---|---|
| `/audit channel` | Sets the channel where changes are posted. | Manage Server |
| `/audit recent` | Shows the last ten changes here. | Manage Server |

See [The audit log](audit.md).

## `/tokens`

| Command | What it does | Needs |
|---|---|---|
| `/tokens create` | Makes a token that acts as you, for an AI assistant or another program. | nothing |
| `/tokens list` | Lists your tokens; with `everyone:true`, everyone's. | nothing; Manage Server for `everyone` |
| `/tokens revoke` | Ends a token. | nothing for your own; Manage Server for someone else's |

See [Connect an AI assistant](ai.md).

## `/admin`

These help AI assistants and programs find their way around a server, and they work as commands too.

| Command | What it does | Needs |
|---|---|---|
| `/admin describe_guild` | Lists the server's channels and roles, with their IDs. | nothing |
| `/admin find_members` | Finds members whose name starts with what you type. | nothing |
| `/admin job_status` | Shows the progress of a job, such as a confirmed change. | nothing for your own jobs; Manage Server for others' |

AI assistants see these three as the tools `admin_describe_guild`, `admin_find_members` and `admin_job_status`. The other built-in commands work only in Discord.

**Next:** [Announcements](plugins/announcements.md).

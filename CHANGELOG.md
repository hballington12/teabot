# Changelog

Every release of `teabot`, `teabot-announcements` and the instance template, newest first. The versions follow semantic versioning, which `teabot.sdk` keeps from 1.0 (D45). A **For operators** section lists any manual step an upgrade needs (D48).

## Unreleased

The first release.

- A plugin framework for Discord bots. Each action a plugin offers is a slash command, an MCP tool and a service API route at once, behind one call path that checks the member's Discord permissions on every call and records an audit trail.
- `teabot.sdk` 1.0: actions, jobs, per-server config, each plugin's own tables in its own schema and role, and plan then apply for destructive actions.
- Tokens for LLM clients and event backends, tied to a member and narrowed by risk and by action.
- Servers that add and remove the bot, with their data kept for a grace period and then purged.
- `teabot-announcements`: post an announcement now, or schedule it.
- `teabot init`, `teabot run`, `teabot plugins list | purge` and `teabot new-plugin`.
- The instance template, with a quick setup on Docker Compose and a careful one on a bare-metal host with continuous backups.

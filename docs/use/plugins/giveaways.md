# Giveaways

Run giveaways: members enter, and teabot draws the winners when time is up. Turn it on with `/plugins enable plugin:giveaways`.

## Start a giveaway

```text
/giveaways start channel:#giveaways prize:Discord Nitro winners:2 minutes:1440
```

teabot announces the giveaway in the channel, with its number and how to enter, and replies with when it ends.

| Option | What it is |
|---|---|
| `channel` | Where to announce it. |
| `prize` | What the winners get, up to 200 characters. |
| `winners` | How many winners to draw, from 1 to 20. `1` if left out. |
| `minutes` | How long it runs, up to a week. The server's `default_minutes` if left out. |

## Enter a giveaway

```text
/giveaways enter giveaway:3
```

teabot replies `You're in. Good luck!` Each member can enter once. Entering again, or entering a giveaway that has ended, replies `You are already in, or that giveaway is not running.` A member with the excluded role is told `Your role cannot enter giveaways here.`

## See the running giveaways

```text
/giveaways list
```

teabot shows the running giveaways to the whole channel, one a line: its number, prize, end time, and entrants. Discord shows the end time in each member's own time zone.

```text
- 3 · Discord Nitro · 15 November 2026 12:00 · 5
```

## The draw

When time is up, teabot picks the winners at random. It announces them in the giveaway's channel, and mentions only the winners. If fewer members entered than there are winners, all of them win. If nobody entered, it says so.

## Cancel a giveaway

```text
/giveaways cancel giveaway:3
```

teabot shows a plan of what it will cancel. Confirm it within 15 minutes, and the giveaway and its draw are cancelled. See [Confirming changes](../confirming.md). The giveaway's announcement stays in the channel; delete it if you like.

## Who can use it

| Command | Needs |
|---|---|
| `/giveaways start` | Manage Messages |
| `/giveaways cancel` | Manage Messages |
| `/giveaways enter` | nothing |
| `/giveaways list` | nothing |

`enter` and `list` need nothing, so every member sees `/giveaways`.

## Settings

Change them with `/plugins config plugin:giveaways setting:<name> value:<value>`.

| Setting | Default | What it does |
|---|---|---|
| `default_minutes` | `60` | How long a giveaway runs when `start` is not told. From 1 to 10080, a week. |
| `excluded_role` | none | A role ID. Members with this role may not enter. |

```text
/plugins config plugin:giveaways setting:excluded_role value:123456789012345678
```

## For AI assistants

The tools are `giveaways_start`, `giveaways_enter`, `giveaways_list` and `giveaways_cancel`.

**Next:** [Roles](roles.md).

# The audit log

At the end of this page, every change made through teabot is posted to a channel your staff can read.

teabot records every action run through it: who ran it, what they asked for, and what happened. These commands need **Manage Server**.

## Choose the audit channel

```text
/audit channel channel:#staff-log
```

teabot replies `Audit posts now go to #staff-log.` Pick a channel only your staff can see. From then on, every change appears there as a post:

| Field | What it shows |
|---|---|
| title | the action, such as `giveaways.start` |
| Member | who ran it |
| Outcome | `ok`, `refused` or `error` |
| Front door | how it came in: `slash` for a command, `component` for a button, `mcp` for an AI assistant, `service` for another program, `cli` when the operator changed something on the bot's machine |
| Input | what was asked for, with channels, roles and members as their IDs |
| Error | what went wrong, when something did |

Actions that only look things up, such as `/plugins list`, are recorded but never posted, which keeps the channel readable. If the audit channel is deleted, posts stop until you choose another.

## See recent changes

```text
/audit recent
```

teabot shows the last ten entries in your server, including plans nobody confirmed, as `planned`:

```text
#42 giveaways.start ok by @Sam
#41 plugins.enable ok by @Alex
```

## How long it is kept

teabot keeps changes for a year, and look-ups for 30 days. [Removing teabot](index.md#removing-teabot) says what happens to your server's data when the bot leaves.

**Next:** [Connect an AI assistant](ai.md).

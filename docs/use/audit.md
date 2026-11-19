# The audit log

At the end of this page, every change made through teabot is posted to a channel your staff can read.

teabot records every action run through it: who ran it, what they asked for, and what happened. These commands need **Manage Server**.

## Choose the audit channel

```text
/audit channel channel:#staff-log
```

teabot replies `Audit posts now go to #staff-log.` Pick a channel only your staff can see. From then on, every change appears there, one line each:

```text
**wom.link** · @Sam · mcp
🟢 names: `Void Cho` · member: @Void · #88
🟢 names: `Xiuol` · member: @Xiuol · #89
```

- **The first line** names the action, who ran it, and how it came in: `slash` for a command, `component` for a button, `mcp` for an AI assistant, `service` for another program, `cli` when the operator changed something on the bot's machine.
- **Each entry** shows its outcome, what was asked for, with members, roles and channels as mentions that notify nobody, any error, and its audit number:
  - 🟢 ok;
  - 🟠 refused;
  - 🔴 error;
  - 🔵 handed off to work that finishes later.
- **Entries close together share a post.** Changes by one member for one action, through one front door, up to two minutes apart, are added to the same post, up to ten.

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

teabot keeps changes for a year, and look-ups for 30 days. [Removing teabot](#removing-teabot) says what happens to your server's data when the bot leaves.

## Removing teabot

teabot keeps a few things about your server: which plugins are on and their settings, what each plugin stores, the AI assistant tokens your members made, and this audit log.

If you remove teabot from your server, all of it is deleted 30 days later. That is the default, and the operator can change it. If you add teabot back before then, everything is as it was.

**Next:** [Connect an AI assistant](ai.md).

# Members and permissions

teabot keeps a directory of your server's members: who is here, who has left, their roles, and how each joined. It also keeps their history: joins, leaves, kicks, bans, timeouts, role changes and nickname changes. An [AI assistant](ai.md) can then answer questions such as "who joined through the clan invite last month and still has no rank?" or "who had the Raiders role before it was deleted?".

It can also show every channel's permissions, and the server as a set of roles sees it, as Discord's **View server as role** does.

These tools need **Manage Server**, as Discord's own member settings do, and every use is in the [audit log](audit.md).

## Ask an assistant

Once your assistant is [connected](ai.md), ask in your own words:

```text
How many members do we have per rank?
Who joined in October and has no roles?
Who invited the most people this year?
When did Sam get the Officer role, and who gave it?
Who left in the last week?
Which channels can Raiders see that Members cannot?
```

The assistant uses these tools:

| Tool | What it answers |
|---|---|
| `admin_members` | Members, filtered by roles, when they joined, account age, how they joined (invite, vanity URL, server discovery, a bot), who invited them, name, boosting, timed out, membership screening, bots, and members who left. It sorts and pages them, 100 a page, or counts them by role, join method, inviter or join month. |
| `admin_member_history` | One member's history, or the whole server's, between two dates, by kind of event. Each event says who did it, when Discord's audit log names them. |
| `admin_channels` | Every category and channel, in Discord's order, with each permission overwrite: for each role or member, what is allowed and denied. |
| `admin_view_as` | For one or more roles, each channel, visible or hidden, and what those roles may do there. |

## How current it is

- **The first copy.** After teabot joins your server, or this teabot is upgraded, it copies the member list once. Until that copy is done, the member tools say how far it has got, and answer nothing else. History starts when it finishes, so joins and role changes from before then are unknown.
- **Kept current.** teabot hears every join, leave and member update as it happens. Each day, and whenever teabot restarts, it also compares its copy with Discord's member list, and records what changed meanwhile. A change found that way says it happened between two times.
- **Every answer says how far to trust it:** whether the first copy is done, when history starts, when the copy was last compared with Discord's, and whether it may be behind.
- **Who did it.** Kicks, bans, timeouts, role changes and nickname changes name who made them when teabot has **View Audit Log**. Without it, a kick shows as leaving. A change teabot made for someone, such as a confirmed role change, names them.
- **How someone joined** comes from Discord's member search, and is filled in within a day of joining. Discord does not know it for very old joins, which show `unknown`.

## Channel permissions

`admin_view_as` works as Discord does for a set of roles:

1. The server permissions of the roles together, with @everyone's, are the start. **Administrator** grants everything, everywhere.
2. In each channel, @everyone's overwrite applies, then the roles' overwrites together: their denies, then their allows.
3. Without **View Channel**, nothing else is left in that channel. In a text channel, without **Send Messages**, embedding links, attaching files, mentioning everyone and text-to-speech go too.

A member's own overwrite, and the server owner, who has every permission, are outside a view as roles.

## Privacy

The directory holds data on every member, not only those who use teabot: their names, roles, when and how they joined, and their history in your server. It keeps no message text, and no history of usernames or display names, only nicknames. Members who leave are kept for as long as the operator chooses, a year unless they say otherwise, and the instance's privacy policy says how long. A member's [data deletion](../host/production.md#delete-a-members-data) removes them from the directory in every server.

**Next:** [Built-in commands](commands.md).

# Roles

Post a role picker: a message with a button for each role, which members press to take the role, and press again to give it back. Give a role to members, or take it away, from a few named members to thousands chosen by a filter. Turn it on with `/plugins enable plugin:roles`.

## Post a role picker

```text
/roles post channel:#roles title:Pick your pings roles_1:@Raids roles_2:@Bossing roles_3:@Events
```

teabot posts the title, a line on how it works, and a button for each role, and replies with a link to it.

| Option | What it is |
|---|---|
| `channel` | Where to post it. |
| `title` | The post's title, up to 100 characters. |
| `roles_1` to `roles_10` | The roles members can take. At least one. Add more later with `/roles add`, up to 25. |
| `note` | A line under the title, such as what the roles are for. |

## Taking a role

A member presses a role's button. teabot replies, privately, `You now have Raids.` Pressing it again replies `Raids removed.` and takes the role back. Anyone who can see the post can press its buttons.

## Which roles can be offered

A button gives a member a role they could not give themselves, so teabot offers only roles that are safe to give out. It refuses a role, and says why, when:

- Discord or an integration manages it, such as a bot's own role or the booster role.
- It grants a moderator's permission, such as Administrator, Manage Server, Manage Roles, Manage Messages, Kick Members or Ban Members.
- It sits at or above teabot's highest role. Move teabot's role above it in **Server Settings**, then **Roles**.
- It sits at or above the highest role of the admin offering it, unless they own the server.

A press checks these again, so a role given a moderator's permission after it was posted stops working.

## Change a role picker

```text
/roles add post:1 role:@Skilling
/roles remove post:1 role:@Bossing
```

teabot updates the post in place. Removing a role takes its button away; members who took the role keep it. The `post` option suggests the server's role pickers as you type.

## See and delete role pickers

```text
/roles list
/roles delete post:1
```

`/roles list` shows each role picker's number, title, channel and how many roles it offers. `/roles delete` shows a plan first, then deletes the post. Members keep the roles they took. See [Confirming changes](../confirming.md).

## Give or take a role

```text
/roles give role:@Friends members_1:@sam members_2:@ann
/roles take role:@Friends members_1:@sam
```

Up to ten named members at once. teabot shows a [plan](../confirming.md) first: who changes, and who is skipped because they already have the role, or lack it. Confirm, and it changes them in seconds. `/roles add` and `/roles remove` change a role picker, not members.

teabot gives or takes a role for you only within what you could do yourself: the role must sit below your highest role, and to give a role, you must have every permission it grants. The server's owner may give any role teabot can.

## Change everyone a filter matches

An [AI assistant](../ai.md) can change every present member a filter matches, such as "take Friends from everyone who has Clan Member", with the tools `roles_give_matching` and `roles_take_matching`. They take the same filter as `admin_members` in the [member directory](../members.md), so the assistant can count who matches first. They also work through the service API and on the site.

- **Up to 10,000 members.** Split a larger change, such as by join date.
- **People only**, unless the filter asks for bots too. Members are never chosen by name, which they could change.
- **The plan** says the change in a sentence, how many members change and how many already have the role, a few of their names, how long it should take, and whether the role grants a moderator's permission.
- **It runs a few members a second,** since Discord allows 10 role changes every 10 seconds in a server. 3,000 members take about an hour. A restart or a deploy picks it up where it was.
- **Each member is checked again** as teabot reaches them, so a member who no longer matches is skipped. Members who joined after the plan are in the change if the filter matches them.
- **It stops** when you lose Manage Roles or Manage Server, when the token that confirmed it expires or is revoked, when the role is moved above teabot or deleted, or when the plugin is turned off for a day. Its outcome goes to the [audit log](../audit.md).
- **Never a moderator's role through an assistant.** Through an AI assistant, teabot refuses a role that grants a moderator's permission, giving or taking it, since an assistant confirms its own plans. Give such roles in Discord.

`roles_list_changes` shows the server's latest changes, with how many members each changed, how many had left, and how many it skipped. `roles_stop` stops one between bursts. `roles_revert` undoes a finished change for the members it changed, within 30 days of it ending: a member who already had the role before counts as changed, so a revert can take away a role they had.

An assistant needs a token made with `max_risk:destructive` to change roles. See [Connect an AI assistant](../ai.md#limit-a-token).

## Who can use it

| Command | Needs |
|---|---|
| `/roles post` | Manage Roles |
| `/roles add` | Manage Roles |
| `/roles remove` | Manage Roles |
| `/roles list` | Manage Roles |
| `/roles delete` | Manage Roles |
| `/roles give`, `/roles take` | Manage Roles |
| `roles_give_matching`, `roles_take_matching` | Manage Roles and Manage Server |
| `roles_list_changes`, `roles_stop`, `roles_revert` | Manage Roles |

Pressing a button needs nothing: it runs `/roles toggle`, which only the buttons reach, so it is no command and no AI assistant tool. Every command needs Manage Roles, so members without it never see `/roles`.

## Settings

None.

## For AI assistants

The tools are `roles_post`, `roles_add`, `roles_remove`, `roles_list` and `roles_delete` for role pickers, and `roles_give`, `roles_take`, `roles_give_matching`, `roles_take_matching`, `roles_list_changes`, `roles_stop` and `roles_revert` for members.

**Next:** [Troubleshooting](../troubleshooting.md).

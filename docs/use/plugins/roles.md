# Roles

Post a role picker: a message with a button for each role, which members press to take the role, and press again to give it back. Turn it on with `/plugins enable plugin:roles`.

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

## Who can use it

| Command | Needs |
|---|---|
| `/roles post` | Manage Roles |
| `/roles add` | Manage Roles |
| `/roles remove` | Manage Roles |
| `/roles list` | Manage Roles |
| `/roles delete` | Manage Roles |
| `/roles toggle` | nothing |

`/roles toggle` is what each button runs, and it works as a command too, for a role still offered on that post. Since it needs nothing, every member sees `/roles`.

## Settings

None.

## For AI assistants

The tools are `roles_post`, `roles_add`, `roles_remove`, `roles_list`, `roles_delete` and `roles_toggle`.

**Next:** [Troubleshooting](../troubleshooting.md).

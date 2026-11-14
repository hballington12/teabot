# Who can use what

At the end of this page, you know who can use each command, and how to change it.

## The rule

- Each action, such as `/giveaways start`, needs a Discord permission. teabot checks it every time the action runs.
- Discord shows a command, such as `/giveaways`, to a member who has the permissions its actions all need. So if one of its actions needs nothing, as `/giveaways enter` does, everyone sees `/giveaways`.
- Discord's **Integrations** settings change who sees a command, and in which channels.

A member who runs an action they lack the permission for gets a private reply saying so, and nothing happens.

[Built-in commands](commands.md) and each plugin's page list the permission every action needs.

## Let a role use a command

Give the role the permission the action needs.

1. Open **Server Settings**, then **Roles**, and choose the role.
2. Open **Permissions**, and turn on the permission.
3. Save.

For example, `/giveaways start` needs **Manage Messages**. Give your giveaway hosts' role Manage Messages, and they can start giveaways. Manage Messages also lets them delete anyone's messages, so give it to roles you trust.

It must be the role's own permission, for the whole server. A channel's permission settings do not count.

teabot checks the member's roles as they are at that moment. Take a role away, and its commands stop working for that member at once.

## Limit who sees a command, or where

1. Open **Server Settings**, then **Integrations**, choose teabot, then **Manage**.
2. Choose a command, such as `/giveaways`. Discord lists each command as a whole, so `/giveaways start` and `/giveaways enter` are limited together.
3. Choose the roles, members or channels it is limited to.

This changes who sees a command. It cannot let anyone run an action teabot's own check refuses.

An AI assistant acts as the member who made its token, with that member's permissions. See [Connect an AI assistant](ai.md).

**Next:** [Confirming changes](confirming.md).

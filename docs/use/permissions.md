# Who can use what

At the end of this page, you know who can use each command, and how to change it.

## The rule

- A member sees a command if they have the Discord permissions all of its actions share.
- Discord's **Integrations** settings change who sees a command, and in which channels.
- teabot still checks each action's own permission every time it runs.

So a command with an action anyone may use, such as `/giveaways enter`, is shown to everyone. A member who runs an action they lack the permission for gets a private reply saying so, and nothing happens.

[Built-in commands](commands.md) and each plugin's page list the permission every action needs.

## Let a role use a command

Give the role the permission the action needs.

1. Open **Server Settings**, then **Roles**, and choose the role.
2. Open **Permissions**, and turn on the permission.
3. Save.

For example, `/giveaways start` needs **Manage Messages**. Give your giveaway hosts' role Manage Messages, and they can start giveaways.

teabot checks the member's roles as they are at that moment. Take a role away, and its commands stop working for that member at once.

## Limit who sees a command, or where

1. Open **Server Settings**, then **Integrations**, and choose teabot.
2. Choose a command.
3. Choose the roles, members or channels it is limited to.

This changes who sees a command. It cannot let anyone run an action teabot's own check refuses.

## AI assistants

An AI assistant acts as the member who made its token, with that member's permissions at that moment. See [Connect an AI assistant](ai.md).

**Next:** [Confirming changes](confirming.md).

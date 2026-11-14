# Troubleshooting

Each problem below starts with what you see.

## A command does not appear

- **It belongs to a plugin.** Turn the plugin on with `/plugins enable`. See [Turn on plugins](plugins.md).
- **You lack its permissions.** A member sees a command only with the permissions all its actions share. See [Who can use what](permissions.md).
- **You just turned it on.** Discord can take a minute. Reload Discord with ++ctrl+r++, or ++cmd+r++ on macOS.
- **Someone limited it.** Check **Server Settings**, then **Integrations**, then teabot.

## "... needs permissions you do not have"

The action needs a Discord permission you do not have. [Built-in commands](commands.md) and each plugin's page say which. Ask an admin to give your role that permission.

## A plugin says "not loaded"

The plugin failed to load on the operator's side, and cannot be turned on. The reason follows `not loaded`. Tell the operator.

## "That did not work. The error is in the audit log."

Something went wrong inside teabot. Run `/audit recent`, or look in your [audit channel](audit.md): the entry's **Error** field says what happened. Pass it to the operator if it looks like a bug.

## "That plan no longer exists"

The plan expired, or was already used. Run the action again for a new plan. See [Confirming changes](confirming.md).

## "That form has expired"

A form for long text lasts 15 minutes. Run the command again.

## teabot cannot post in a channel

Check the channel's permissions. The bot's role needs **View Channel** and **Send Messages** there.

## Two bots answer every command

Two teabots are in your server. Remove one.

## An AI assistant cannot connect

- The address ends in `/mcp`. If teabot's reply said it works only on the bot's machine, ask the operator for a public address.
- Check the token has not expired or been revoked, with `/tokens list`.
- The header is `Authorization: Bearer ` followed by the whole token.

## An AI assistant's change was refused

The token's limits refused it. A token made with `max_risk:read` can only look things up. Make a new token with the limits you need. See [Limit a token](ai.md#limit-a-token).

## Still stuck

If you run the bot yourself, see the [operator's troubleshooting](../host/troubleshooting.md). Otherwise, pass what you saw to whoever runs it.

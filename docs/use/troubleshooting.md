# Troubleshooting

Each problem below starts with what you see.

## A command does not appear

- **It belongs to a plugin.** Turn the plugin on with `/plugins enable`. See [Turn on plugins](plugins.md).
- **You lack its permissions.** A member sees a command only with the permissions all its actions share. See [Who can use what](permissions.md).
- **You just turned it on.** Discord can take a minute. Reload Discord with ++ctrl+r++, or ++cmd+r++ on macOS.
- **Someone limited it.** Check **Server Settings**, then **Integrations**, then teabot.

## "... needs permissions you do not have"

The action needs a Discord permission you do not have. [Built-in commands](commands.md) and each plugin's page say which. Ask an admin to give your role that permission.

## "... is not enabled in this server"

The plugin was turned off, and Discord still showed its command for a moment. Turn it on with `/plugins enable`, or reload Discord.

## A plugin says "not loaded"

The plugin failed to load on the operator's side, and cannot be turned on. The reason follows `not loaded`. Tell the operator.

## "That did not work. The error is in the audit log."

Something went wrong inside teabot. Look in your [audit channel](audit.md): the post's **Error** field says what happened. Choose an audit channel first if you have none, since `/audit recent` does not show errors. Pass the error to the operator if it looks like a bug.

## "that plan is more than 15 minutes old"

The plan expired, or, with "that plan has already been applied", was already used. Run the action again for a new plan. See [Confirming changes](confirming.md).

## "That form has expired"

A form for long text lasts 15 minutes. Run the command again.

## "I am not allowed to post in that channel."

The bot's role needs **View Channel** and **Send Messages** there. This happens only if the bot was added without **Administrator**; add it again with the invite link and leave Administrator ticked.

## Every command shows twice

Two teabots are in your server. Remove one.

## An AI assistant cannot connect

- The address ends in `/mcp`. If teabot's reply said it works only on the bot's machine, ask the operator for a public address.
- Check the token has not expired or been revoked, with `/tokens list`.
- The header is `Authorization: Bearer ` followed by the whole token.

## "this token may not use destructive actions"

The token's limits refused the change. A token made with the default `max_risk:write` cannot use actions that change a lot, such as cancelling a giveaway, and one made with `read` can only look things up. Make a new token with the limits you need. See [Limit a token](ai.md#limit-a-token).

## Still stuck

If you run the bot yourself, see the [operator's troubleshooting](../host/troubleshooting.md). Otherwise, pass what you saw to whoever runs it.

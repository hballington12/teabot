# Connect an AI assistant

At the end of this page, an AI assistant such as Claude Code can use teabot in your server, as you.

teabot's plugin actions, the `/admin` look-ups, and the [member directory and channel permissions](members.md), are also tools an AI assistant can call, through MCP, the protocol AI assistants use for tools. `/plugins`, `/audit` and `/tokens` work only in Discord. The assistant acts as you, with your permissions in your server at the moment of each call, and every call is in the [audit log](audit.md).

## 1. Make a token

In your server:

```text
/tokens create label:claude
```

teabot replies, privately, with the token and what to paste. Only you see it, and only this once.

## 2. Paste it into your assistant

=== "Claude Code"

    [Install Claude Code](https://docs.claude.com/en/docs/claude-code/setup) first. Then, in a terminal (on Windows, in WSL), run the two lines teabot gave you, which have your bot's address in them. The first waits for you to paste the token and press ++enter++. It does not show the token, so it never lands in your shell's history:

    ```bash
    read -rs TEABOT_TOKEN
    claude mcp add --transport http teabot https://teabot.example.org/mcp --header "Authorization: Bearer $TEABOT_TOKEN"
    ```

    Then, in Claude Code, `/mcp` shows `teabot` as connected. Claude Code keeps the token in its own settings from then on.

=== "Other MCP clients"

    Give your client the address and the header from teabot's reply:

    ```text
    address: https://teabot.example.org/mcp
    header:  Authorization: Bearer <your token>
    ```

If the reply says the address works only on the machine running teabot, the operator has not given teabot a public address yet. Ask them to set one, as in [HTTPS](../host/production.md#https).

## What a token can do

- It acts in the one server you made it in, as you. Lose a permission, and the token loses it too.
- It lasts 30 days, unless you say otherwise.
- It may use look-ups and changes that are easy to undo. For actions that change a lot, such as cancelling a giveaway, make it with `max_risk:destructive`. Those show a [plan](confirming.md) first, and the assistant is told to show it to you and wait for your agreement.

## Limit a token

```text
/tokens create label:reports max_risk:read days:7
/tokens create label:events actions:giveaways.start,giveaways.list
```

| Option | What it does |
|---|---|
| `max_risk` | `read` for look-ups only, `write` for changes that are easy to undo (the default), `destructive` for everything |
| `actions` | only these actions, comma-separated, by the names the audit log uses, such as `giveaways.start` |
| `days` | how many days until it expires, up to 365 |

## See and end your tokens

```text
/tokens list
/tokens revoke token_id:ab12cd34
```

`/tokens list` shows your tokens with their ids. `/tokens revoke` ends one at once, and its `token_id` option suggests your tokens by label as you type. With Manage Server, `/tokens list everyone:true` shows everyone's, and you can revoke any of them.

**Next:** [Built-in commands](commands.md).

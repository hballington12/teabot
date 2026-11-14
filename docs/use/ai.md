# Connect an AI assistant

At the end of this page, an AI assistant such as Claude Code can use teabot in your server, as you.

Every teabot action is also a tool an AI assistant can call, through MCP, the protocol AI assistants use for tools. The assistant acts as you, with your permissions in your server at the moment of each call, and every call is in the [audit log](audit.md).

## 1. Make a token

In your server:

```text
/tokens create label:claude
```

teabot replies, privately, with the token and what to paste. Only you see it, and only this once.

## 2. Paste it into your assistant

=== "Claude Code"

    In a terminal, run the two lines teabot gave you. The first waits for you to paste the token, and does not show it, so the token never lands in your shell's history:

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
- Actions that change a lot show a [plan](confirming.md) first. The assistant is told to show it to you and wait for your agreement.

## Limit a token

```text
/tokens create label:reports max_risk:read days:7
/tokens create label:events actions:giveaways.start,giveaways.list
```

| Option | What it does |
|---|---|
| `max_risk` | `read` for look-ups only, `write` for changes that are easy to undo (the default), `destructive` for everything |
| `actions` | only these actions, comma-separated |
| `days` | how many days until it expires, up to 365 |

## See and end your tokens

```text
/tokens list
/tokens revoke token_id:ab12cd34
```

`/tokens list` shows your tokens with their ids. `/tokens revoke` ends one at once. With Manage Server, `/tokens list everyone:true` shows everyone's, and you can revoke any of them.

**Next:** [Built-in commands](commands.md).

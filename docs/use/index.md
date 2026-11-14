# Add teabot to your server

This section is for server admins: adding teabot to a Discord server and using it. You need no programming. At the end of this page, teabot is in your server and answering.

## Which teabot?

A public teabot that anyone can add is on its way, but it is not open yet. Watch the [repository](https://github.com/hballington12/teabot) to hear when it opens.

Until then, a teabot is run by someone: a friend, your community, or you. That person is its **operator**. To run your own, see the [Quick start](../host/index.md).

## Add it

!!! note "Before you start"

    - You need **Manage Server** in the Discord server.
    - Ask the operator for the bot's **invite link**. If you run the bot yourself, it is the link its setup printed.

1. Open the invite link. Discord asks which server to add the bot to.
2. Choose your server. Leave **Administrator** ticked, and choose **Authorize**. The bot joins, with a role of its own named after it.
3. Open **Server Settings**, then **Roles**. Drag the bot's role below your own role and your senior staff's roles, and save.

teabot asks for **Administrator**, so its plugins can do their work without asking for more later. Step 3 is what limits it: a bot can never change a member or a role whose role is above its own.

!!! warning

    Add only one teabot to a server. With two, every command shows twice, once for each bot.

## Check it works

Type `/plugins list` in any channel. teabot replies with the plugins it has, and whether each is on:

```text
announcements disabled
giveaways disabled
```

Only you see the reply. Most of teabot's replies are private to the member who ran the command.

## Removing teabot

teabot keeps a few things about your server: which plugins are on and their settings, what each plugin stores (such as giveaways and their entries), the AI assistant tokens your members made, and the [audit log](audit.md).

If you remove teabot from your server, all of it is deleted 30 days later. That is the default, and the operator can change it. If you add teabot back before then, everything is as it was.

**Next:** [Turn on plugins](plugins.md).

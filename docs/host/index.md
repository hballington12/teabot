# Quick start

At the end of this page, your own teabot is running and you have the link that invites it to your server. It takes about 15 minutes.

!!! note "Before you start"

    You need:

    - Linux or macOS. On Windows, use [WSL](https://learn.microsoft.com/windows/wsl/install).
    - [Docker](https://docs.docker.com/get-docker/), with Compose v2: `docker compose version` should work.
    - `curl`.
    - A Discord server where you have **Manage Server**. A test server of your own is best for a first run.

## 1. Download the template

```bash
mkdir my-teabot && cd my-teabot
curl -sL https://github.com/hballington12/teabot/releases/latest/download/teabot-template.tar.gz | tar xz
```

This folder is now your instance: your bot's settings, plugins and deploy files. Keep it in git. Its `.gitignore` keeps the secret files out.

## 2. Create the Discord application

1. Open the [Discord developer portal](https://discord.com/developers/applications) and choose **New Application**. Give it a name.
2. Open the **Bot** tab.
3. Choose **Reset Token**, and copy the token. You paste it in step 3.

    !!! warning

        Anyone with the token controls your bot. Keep it like a password.

4. Turn on **Server Members Intent**, and save. teabot needs it to see members join and leave.
5. Leave **Message Content Intent** off. No teabot plugin reads messages.
6. Turn **Public Bot** off, unless other people should be able to invite your bot.

## 3. Run the setup

```bash
./setup.sh
```

It asks for the token, then sets up and starts everything:

```text
Paste your Discord bot token (it is not shown):
wrote .env
wrote teabot.env

==> Building the bot's image
==> Starting Postgres
==> Creating the database roles
database ready
==> Starting teabot

==> teabot is running
Invite it to your server with this link:
    https://discord.com/oauth2/authorize?client_id=...&scope=bot+applications.commands&permissions=8
```

- `teabot.env` holds the bot's settings and its token. [Settings](settings.md) explains each one.
- `.env` holds the database password that `setup.sh` generated. Keep it: the database only opens with that password.
- If a step fails, fix what it says and run `./setup.sh` again. It keeps what it already wrote.

## 4. Invite it

Open the link `setup.sh` printed, and follow [Add teabot to your server](../use/index.md). That page also shows your server's admins how to turn on plugins.

**Next:** [Turn on plugins](../use/plugins.md), then [Run it in production](production.md) before a live server depends on it.

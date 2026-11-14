# Bare-metal host

At the end of this page, teabot runs on a dedicated Ubuntu 24.04 server with HTTPS and continuous backups, and you deploy to it with one command. This is the careful alternative to Docker Compose.

The template's `deploy/bare-metal/` folder sets up:

- Postgres 16, reachable only on the server itself
- Caddy, for HTTPS
- teabot as a hardened systemd service
- pgBackRest, which streams every database change to object storage, so a lost server costs about a minute of data

!!! note "Before you start"

    You need:

    - A fresh Ubuntu 24.04 server you can reach as root over SSH.
    - A DNS record for your bot's hostname, such as `teabot.example.org`, pointing at the server.
    - Your instance in a GitHub repository, made from the template as in the [quick start](index.md#1-download-the-template), with your Discord application created.
    - An S3-compatible bucket for backups, such as DigitalOcean Spaces, with an access key.

## 1. Set up the server

From your instance's folder, copy it to the server and run the setup as root:

```bash
rsync -a --exclude .git --exclude .venv --exclude teabot.env ./ root@host:/root/teabot-setup/
ssh root@host /root/teabot-setup/deploy/bare-metal/setup-host.sh teabot.example.org git@github.com:you/my-teabot.git
```

The first run stops and prints a deploy key. Add it to your instance's repository on GitHub, under **Settings**, then **Deploy keys**, as read-only. Then run the same `ssh` command again.

It installs Postgres, pgBackRest, git and uv, clones your instance into `/opt/teabot`, creates the database, adds the Caddy site and installs the service.

## 2. Give it the bot token

```bash
ssh -t root@host /opt/teabot/deploy/bare-metal/set-discord-token.sh
```

It asks for the token, then starts the bot, and prints the invite link. Open it and follow [Add teabot to your server](../use/index.md).

## 3. Turn on backups

```bash
ssh -t root@host /opt/teabot/deploy/bare-metal/setup-backups.sh <bucket> <region>
```

It asks for the bucket's access key, and generates an encryption passphrase.

!!! warning

    Copy the passphrase somewhere safe. Without it, no backup can be restored.

## 4. Prove the backups work

From a machine with Docker:

```bash
deploy/bare-metal/restore-drill.sh root@host
```

It restores the latest backup into a scratch container, and checks it against the server. Run it after setup, and again now and then.

## Deploy a change

Commit and push your instance, then from its folder:

```bash
deploy/bare-metal/deploy.sh root@host
```

It pulls `main` on the server, installs the locked versions, restarts the bot, and waits until `/healthz` answers. An upgrade is the same, after locking the new version:

```bash
docker compose run --rm uv lock --upgrade-package teabot
git commit -am "Upgrade teabot" && git push
deploy/bare-metal/deploy.sh root@host
```

Read the [release notes](changelog.md) first, for any step a release needs by hand.

## Where things are

- The secrets live on the server only: `/etc/teabot/teabot.env` and `/etc/pgbackrest/conf.d/secrets.conf`.
- `/healthz` answers on the server itself: `curl -s http://127.0.0.1:8780/healthz`.
- The bot's log: `journalctl -u teabot`.

**Next:** [Release notes](changelog.md).

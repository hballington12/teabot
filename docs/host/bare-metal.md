# Bare-metal host

At the end of this page, teabot runs on a dedicated Ubuntu 24.04 server with HTTPS and continuous backups, and you deploy to it with one command. This is the careful alternative to Docker Compose.

The template's `deploy/bare-metal/` folder installs and sets up:

- Postgres 16, reachable only on the server itself
- Caddy, which gets the HTTPS certificate
- teabot as a hardened systemd service
- pgBackRest, which streams every database change to object storage, so a lost server costs about a minute of data

!!! note "Before you start"

    You need:

    - A fresh Ubuntu 24.04 server you can reach as root over SSH, with ports 80 and 443 open.
    - A DNS record for your bot's hostname, such as `teabot.example.org`, pointing at the server.
    - Your Discord application, created as in the [quick start](index.md#2-create-the-discord-application).
    - A DigitalOcean Spaces bucket for backups, with an access key. The backup settings are written for Spaces.
    - Docker on your own machine, for the `uv` commands and the restore drill.

## 1. Put your instance on GitHub

[Download the template](index.md#1-download-the-template), lock it to the newest teabot, then push it to a new, private GitHub repository:

```bash
TEABOT_UID=$(id -u) TEABOT_GID=$(id -g) docker compose run --rm uv lock
git init
git add .
git commit -m "My teabot instance"
git remote add origin git@github.com:you/my-teabot.git
git push -u origin main
```

## 2. Set up the server

From your instance's folder, copy it to the server and run the setup as root:

```bash
rsync -a --exclude .git --exclude .env --exclude teabot.env --exclude backups ./ root@host:/root/teabot-setup/
ssh root@host /root/teabot-setup/deploy/bare-metal/setup-host.sh teabot.example.org git@github.com:you/my-teabot.git
```

The first run stops and prints a deploy key. Add it to your repository on GitHub, under **Settings**, then **Deploy keys**, as read-only. Then run the same `ssh` command again.

It installs Postgres, pgBackRest, Caddy, git and uv, clones your instance into `/opt/teabot`, creates the database, adds the Caddy site and installs the service.

## 3. Give it the bot token

```bash
ssh -t root@host /opt/teabot/deploy/bare-metal/set-discord-token.sh
```

For the [dashboard](production.md#the-dashboard), put the application's OAuth2 client secret in the same way, after adding `https://your.hostname/dashboard/callback` to its redirects:

```bash
ssh -t root@host /opt/teabot/deploy/bare-metal/set-client-secret.sh
```

It asks for the token, starts the bot, and prints the invite link. Open it, choose your server, and authorize, then [place teabot's role](../use/permissions.md#place-teabots-role).

## 4. Turn on backups

With your bucket's name and its region, such as `lon1`:

```bash
ssh -t root@host /opt/teabot/deploy/bare-metal/setup-backups.sh my-teabot-backups lon1
```

It asks for the bucket's access key, and generates an encryption passphrase. Show it once, and copy it to a password manager:

```bash
ssh root@host grep cipher-pass /etc/pgbackrest/conf.d/secrets.conf
```

!!! warning

    Without the passphrase, no backup can be restored.

## 5. Prove the backups work

From your instance's folder, on a machine with Docker:

```bash
deploy/bare-metal/restore-drill.sh root@host
```

It restores the latest backup into a scratch container, and checks it against the server. Run it after setup, and again now and then.

## Deploy a change

Commit and push your instance, then from its folder:

```bash
deploy/bare-metal/deploy.sh root@host
```

It pulls the branch the server cloned, installs the locked versions, restarts the bot, and waits until `/healthz` answers. An upgrade is the same, after locking the new version:

```bash
TEABOT_UID=$(id -u) TEABOT_GID=$(id -g) docker compose run --rm uv lock --upgrade-package teabot
git commit -am "Upgrade teabot" && git push
deploy/bare-metal/deploy.sh root@host
```

The first line runs uv in Docker as your own user, so the lock file stays yours. Read the [release notes](changelog.md) first, for any step a release needs by hand.

## Where things are

- The settings and secrets live on the server only: `/etc/teabot/teabot.env` and `/etc/pgbackrest/conf.d/secrets.conf`. After changing the settings, run `systemctl restart teabot`.
- `/healthz` answers on the server itself: `curl -s http://127.0.0.1:8780/healthz`.
- The bot's log: `journalctl -u teabot`.

**Next:** [Release notes](changelog.md).

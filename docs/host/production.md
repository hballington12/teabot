# Run it in production

At the end of this page, your Docker Compose instance is ready for a live server: reachable over HTTPS, watched, backed up, and easy to upgrade.

The [quick start](index.md) is enough to try teabot. For a dedicated server with continuous backups, see [Bare-metal host](bare-metal.md) instead.

## Keep a second bot for testing

Make a second Discord application, and a second instance from the template, for experiments. A test then never reaches your live server.

Run the test instance on another machine. Every instance made from the template uses the same Docker names, so two on one machine would share one database.

Never invite two teabot instances to one server. Every command would show twice.

## HTTPS

AI assistants and your own services reach teabot over HTTP, on `127.0.0.1:8780`. That works only on this machine. To reach it from anywhere else, put [Caddy](https://caddyserver.com/) in front of it, which gets an HTTPS certificate by itself.

!!! note "Before you start"

    You need a DNS record for your bot's hostname, such as `teabot.example.org`, pointing at this machine, with ports 80 and 443 open to the internet.

1. Install Caddy, as its [install guide](https://caddyserver.com/docs/install) shows for your system.
2. Copy the template's site file into Caddy's folder, with your hostname in place of `teabot.example.org`:

    ```bash
    sed 's/teabot.example.org/your.hostname/' deploy/bare-metal/teabot.caddy | sudo tee /etc/caddy/teabot.caddy
    echo 'import teabot.caddy' | sudo tee -a /etc/caddy/Caddyfile
    sudo systemctl reload caddy
    ```

    The site file forwards everything to teabot, its site, `/mcp` and `/api`, except the health check, which stays on the machine. It keeps the `Host` header that teabot checks:

    ```text title="deploy/bare-metal/teabot.caddy"
    --8<-- "template/deploy/bare-metal/teabot.caddy"
    ```

3. Set the public address in `teabot.env`, then recreate the bot:

    ```ini title="teabot.env"
    TEABOT_PUBLIC_URL=https://your.hostname
    ```

    ```bash
    docker compose up -d --force-recreate bot
    ```

`/tokens create` then gives AI assistants this address.

## Your teabot's site

With a public address, your teabot serves its own site there, at `https://your.hostname/`:

- **The home page**, with your bot's name and avatar, an **Add to your server** button, and its plugins.
- **The plugin browser**, at `/plugins`, with a page for each plugin. Your servers' admins sign in with Discord, choose a server, and turn plugins on and off or change their settings in place, with the same permission checks as `/plugins` and the same [audit log](../use/audit.md).
- **Your privacy policy and terms**, at `/privacy` and `/terms`, from `pages/privacy.md` and `pages/terms.md` in your instance's folder. Each shows, and is linked from every page's footer, once its file exists. Write them in Markdown.
- **`/plugins.json`**, the plugins your teabot runs, which the plugin hub reads to say which plugins a teabot offers.

Your privacy policy should say what the [member directory](../use/members.md#privacy) keeps about every member of the servers your teabot is in, and for how long: `TEABOT_DIRECTORY_RETENTION_DAYS`, a year unless you set it.

The site shows without sign-in. To let admins sign in:

1. In the [Discord developer portal](https://discord.com/developers/applications), open your application, then **OAuth2**.
2. Under **Redirects**, add `https://your.hostname/auth/callback`, and save.
3. Copy the **Client Secret**, resetting it if it shows none, and put it in `teabot.env`:

    ```ini title="teabot.env"
    TEABOT_DISCORD_CLIENT_SECRET=the-client-secret
    ```

4. Recreate the bot:

    ```bash
    docker compose up -d --force-recreate bot
    ```

Without the secret, the site shows, and its pages say to use `/plugins` in Discord. Without a public address, there is no site.

## Watch the health check

```bash
curl -s http://127.0.0.1:8780/healthz
```

It answers `"ok":true` while the bot is connected to Discord and its database, with each plugin's state, the queue's backlog, the memory it uses now and the version:

```json
{"ok":true,"version":"1.5.0","shards":{"0":0.05},"database":true,"queue_backlog":0,"memory_mb":182.4,"plugins":{"announcements":"loaded","roles":"loaded"}}
```

A plugin that failed to load shows why, such as `failed` or `duplicate_id`. A plugin that holds teabot's event loop for a second is logged as `event loop blocked`, with the plugin and the line of its code. One that holds it for thirty seconds stops teabot, which logs every thread's traceback first, and Compose or systemd starts it again. `TEABOT_LOOP_WARN_SECONDS` and `TEABOT_LOOP_LIMIT_SECONDS` change the two limits. The check answers only on this machine, so watch it from here, with a monitoring agent or a cron job. Compose restarts the bot if it stops.

## Upgrade

1. Read the [release notes](changelog.md) for every release since yours. A release's **For operators** part lists any step you must take by hand, such as taking new files from the template. Your version is in `/healthz`.
2. Upgrade and rebuild:

    ```bash
    docker compose run --rm uv lock --upgrade-package teabot
    docker compose up -d --build
    ```

    The bot updates its database when it starts.

3. Check that `/healthz` answers `"ok":true` with the new version, then commit `uv.lock`.

A plugin upgrades the same way, by its package name, such as `--upgrade-package teabot-raffles`. Read its changes first, since it runs inside your bot.

## Back up

All of teabot's data is in its Postgres database: settings, plugin data, tokens and the audit log. Save a copy, with the database roles that own it:

```bash
mkdir -p backups
docker compose exec -T postgres pg_dumpall -U teabot_owner > backups/teabot.sql
```

`.gitignore` keeps `backups/` out of git. To take one every night at 4am, add this line with `crontab -e`, with your instance's folder in place of `/home/you/my-teabot`:

```text
0 4 * * * cd /home/you/my-teabot && docker compose exec -T postgres pg_dumpall -U teabot_owner > backups/teabot-$(date +\%F).sql
```

Copy the backups somewhere else too, such as another machine with `rsync` or a cloud drive. A backup on the same disk is lost with it.

Keep `.env` and `teabot.env` safe with them: the restored database keeps the old passwords, which only those files hold.

To restore on a new machine, clone your instance's repository, and put your `.env`, `teabot.env` and the backup, here `backups/teabot.sql`, in its folder. Then:

```bash
docker compose up -d --wait postgres
docker compose exec -T postgres psql -U teabot_owner -d postgres < backups/teabot.sql
./setup.sh
```

The restore reports that the role `teabot_owner` and the database `teabot` already exist. That is expected: Postgres made them when it started, and the restore fills them in.

## Delete a member's data

Discord expects a bot to delete what it keeps about someone who asks. Run, with their Discord ID:

```bash
docker compose run --rm bot teabot users delete 123456789012345678
```

teabot asks first, then lists what it changed:

```text
Deleted or anonymised:
  giveaways.entries: 2 rows
  audit log: 14 rows
```

- Every plugin's rows that hold the member are deleted, such as their giveaway entries.
- Their tokens are deleted. The audit log keeps what was done, with their ID replaced by `0`.
- Their rows and history in the [member directory](../use/members.md) are deleted. Where others' history names them, as who invited, kicked or banned someone, their ID is replaced by `0`. A member who is still in a server reappears in its directory at their next change or the next daily comparison, with no history before it.
- `--server 987654321098765432` limits it to one server.
- Backups taken earlier still hold the data, until they are rotated out.

## Growing past 100 servers

Discord must verify a bot before it can join more than 100 servers. Apply in the developer portal before you get close.

**Next:** [Bare-metal host](bare-metal.md), or [Release notes](changelog.md).

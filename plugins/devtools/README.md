# teabot-devtools

Development only. It is in the workspace's `dev` group and never in production.

- `/devtools note`: writes to the plugin's own `notes` table in a transaction and returns the server's count.
- `/devtools peek_core`: tries to read `core.jobs` and reports the refusal the plugin role gets (D9). Needs Manage Server.
- `TEABOT_DEVTOOLS_FAIL_SETUP=1` makes `setup` fail, so the bot reports devtools as failed while everything else loads (D14).
- External connections: none (D12).

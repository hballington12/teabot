"""The docs site's plugin hub section, from the hub's catalogue: hub.py [catalogue URL or file] [output folder]

It writes `docs/hub/index.md`, a card for each listed plugin, and `docs/hub/<id>.md`, a page for each. Every page is
built from the catalogue's fields alone, and every value an author wrote is escaped, so nothing from a plugin's
README or description can add HTML or links to the site. When the catalogue cannot be read, the section says so and
the build still passes. Run it before building the docs; the files it writes are not committed.
"""

import html
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

CATALOGUE = "https://teabot-dev.github.io/plugin-hub/catalogue.json"
OUT = Path("docs/hub")
# The public teabot's dashboard, where a guild admin turns a listed plugin on.
DASHBOARD = "https://teabot.tea-osrs.com/dashboard"
HUB_REPO = "https://github.com/teabot-dev/plugin-hub"
PLUGIN_ID = re.compile(r"[a-z][a-z0-9_]{1,31}")
COMMIT = re.compile(r"[0-9a-f]{40}")
SAFE_URL = re.compile(r"https://(github\.com|gitlab\.com|codeberg\.org)/[\w.-]+/[\w.-]+")
RANGE = re.compile(r"[0-9<>=!~,.* ]{1,40}")
MARKDOWN = re.compile(r"([\\`*_{}\[\]()#+!|~>])")


def text(value: Any) -> str:
    """An author's words as plain text: HTML escaped, and Markdown's own characters too, so they make no links,
    emphasis or markup."""
    return MARKDOWN.sub(r"\\\1", html.escape(" ".join(str(value or "").split()), quote=False))


def teabot_range(version: dict[str, Any]) -> str:
    """The teabot versions a plugin version runs on, as written when it is a version range, else unknown."""
    found = str(version.get("teabot", ""))
    return f"`teabot{found}`" if RANGE.fullmatch(found) else "unknown"


def read(source: str) -> dict[str, Any] | None:
    """The catalogue, from a URL or a file, or None when it cannot be read."""
    try:
        if source.startswith("https://"):
            with urllib.request.urlopen(source, timeout=20) as reply:
                return json.loads(reply.read())
        return json.loads(Path(source).read_text())
    except (OSError, ValueError):
        return None


def listed(catalogue: dict[str, Any]) -> list[dict[str, Any]]:
    """The plugins worth a page: a valid id and source, at least one version with a full commit."""
    found: list[dict[str, Any]] = []
    for plugin in catalogue.get("plugins", []):
        versions = [v for v in plugin.get("versions", [plugin]) if COMMIT.fullmatch(str(v.get("commit", "")))]
        valid = PLUGIN_ID.fullmatch(str(plugin.get("id", ""))) and SAFE_URL.fullmatch(
            str(plugin.get("repository", ""))
        )
        if valid and versions:
            found.append({**plugin, "versions": versions})
    return sorted(found, key=lambda p: p["id"])


INTRO = """---
hide:
  - toc
---

# Plugin hub

Plugins that add to what Teabot does, each reviewed by Teabot's maintainers at the exact version listed. The plugins
that come with Teabot, [announcements](../use/plugins/announcements.md) and [roles](../use/plugins/roles.md), are not
listed here: every Teabot has them.

- **Guild admins:** on the public Teabot, every plugin here is ready. Turn one on in the
  [dashboard]({dashboard}), or with [`/plugins enable`](../use/plugins.md).
- **Self-hosters:** install one with `uv run teabot hub add <id>`, or all of them with `uv run teabot hub sync`. See
  [Adding plugins](../host/adding-plugins.md).
- **Plugin developers:** to list yours, see [Publishing a plugin](../plugins/publishing.md).
"""


# Marks a page as written here, so the theme's edit button, which would open a file not in the repository, hides.
GENERATED = '<span class="teabot-generated" hidden></span>'


def card(plugin: dict[str, Any]) -> str:
    newest = plugin["versions"][0]
    return (
        "-   :lucide-puzzle:{ .teabot-badge }\n\n"
        f"    [{text(plugin['id'])}]({plugin['id']}.md)\n\n"
        f"    {text(plugin.get('description')) or 'No description.'}\n\n"
        f"    <small>{text(newest.get('version'))} · "
        f"contacts: {text(newest.get('external_connections')) or 'none given'}</small>\n"
    )


def index(plugins: list[dict[str, Any]], reachable: bool) -> str:
    out = INTRO.format(dashboard=DASHBOARD) + f"\n{GENERATED}\n"
    if not reachable:
        return (
            out
            + "\n!!! warning\n\n    The hub's catalogue could not be read when this page was built. Try again later.\n"
        )
    if not plugins:
        return out + "\nNo plugins are listed yet.\n"
    cards = "\n".join(card(p) for p in plugins)
    return out + f'\n<div class="grid cards teabot-features teabot-hub" markdown>\n\n{cards}\n</div>\n'


def page(plugin: dict[str, Any]) -> str:
    pid = plugin["id"]
    newest = plugin["versions"][0]
    repo = plugin["repository"]
    others = (
        ", ".join(f"`{text(d)}`" for d in newest.get("dependencies", [])) or "nothing beyond Teabot's own"
    )
    rows = "\n".join(
        f"| {text(v.get('version'))} | [`{v['commit'][:12]}`]({repo}/tree/{v['commit']}) | {teabot_range(v)} |"
        for v in plugin["versions"]
    )
    requirement = f"teabot-{pid} @ git+{repo}.git@{newest['commit']}"
    return f"""{GENERATED}
# {text(pid)}

{text(plugin.get("description")) or "No description."}

[Enable in your server]({DASHBOARD}){{ .md-button .md-button--primary }}
[Source]({repo}){{ .md-button }}

- **Version:** {text(newest.get("version"))}
- **Contacts:** {text(newest.get("external_connections")) or "none given"}
- **Installs:** {others}
- **Licence:** {text(plugin.get("licence")) or "not given"}

Every version was reviewed at the commit shown. Teabot installs the newest one its own version runs.

| Version | Commit | Runs on |
|---|---|---|
{rows}

## Turn it on

On the public Teabot it is installed already. In the [dashboard]({DASHBOARD}), choose your server and turn
**{text(pid)}** on, or run this in your server:

```text
/plugins enable plugin:{pid}
```

## Install it on your own Teabot

In your instance's folder:

```bash
uv run teabot hub add {pid}
```

Without uv on the machine:

```bash
docker compose run --rm uv add "{requirement}"
```

Then rebuild with `docker compose up -d --build`. See [Adding plugins](../host/adding-plugins.md).

**Back to:** [the plugin hub](index.md)
"""


def write(catalogue: dict[str, Any] | None, out: Path) -> list[str]:
    """Write the section into `out`, replacing what was there. Returns the plugin ids given pages."""
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.md"):
        old.unlink()
    plugins = listed(catalogue) if catalogue is not None else []
    (out / "index.md").write_text(index(plugins, catalogue is not None))
    for plugin in plugins:
        (out / f"{plugin['id']}.md").write_text(page(plugin))
    return [p["id"] for p in plugins]


if __name__ == "__main__":
    source = sys.argv[1] if len(sys.argv) > 1 else CATALOGUE
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else OUT
    ids = write(read(source), target)
    print(f"plugin hub: {len(ids)} plugins{': ' + ', '.join(ids) if ids else ''}")

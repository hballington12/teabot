"""The docs site's plugin hub section, from the hub's catalogue: hub.py [catalogue URL or file] [output folder]

It writes `docs/hub/index.md`, a card for each listed plugin, and `docs/hub/<id>.md`, a page for each. Every page is
built from the catalogue's fields alone, and every value an author wrote is escaped, so nothing from a plugin's
README or description can add HTML or links to the site. When the catalogue cannot be read, the section says so and
the build still passes. A plugin's page offers it on the official Teabot only when that instance's `/plugins.json`
lists it (D53). Run it before building the docs; the files it writes are not committed.
"""

import html
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, cast

CATALOGUE = "https://teabot-dev.github.io/plugin-hub/catalogue.json"
OUT = Path("docs/hub")
# The official Teabot, one instance among any: its site, and the plugins it offers, which its /plugins.json lists.
OFFICIAL = "https://teabot.tea-osrs.com"
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


def offered(site: str = OFFICIAL) -> set[str] | None:
    """The plugins the official Teabot offers, or None when its list cannot be read, so the pages claim nothing."""
    found = read(f"{site}/plugins.json")
    if found is None:
        return None
    listed: list[Any] = list(found.get("plugins", []))
    return {str(cast(dict[str, Any], p).get("id")) for p in listed if isinstance(p, dict)}


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

Here you can browse plugins for Teabot. To contribute to the plugin hub, see
[Publishing a plugin](../plugins/publishing.md).
"""


# Marks a page as written here, so the theme's edit button, which would open a file not in the repository, hides.
GENERATED = '<span class="teabot-generated" hidden></span>'


def author(plugin: dict[str, Any]) -> str:
    """Who made the plugin: the author its package names, or, for a listing from before the hub asked, the owner
    of its repository."""
    named = str(plugin.get("author") or "").strip()
    return named or str(plugin["repository"]).split("/")[3]


def short(words: str, limit: int = 160) -> str:
    """At most `limit` characters, cut at a word with an ellipsis; the card also clamps it to three lines."""
    if len(words) <= limit:
        return words
    return words[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def card(plugin: dict[str, Any]) -> str:
    """A plugin's card: its icon, title and version on one row, its description, then who made it."""
    newest = plugin["versions"][0]
    description = text(short(" ".join(str(plugin.get("description") or "").split()))) or "No description."
    return (
        f"-   :lucide-puzzle:{{ .teabot-badge }} [{text(plugin['id'])}]({plugin['id']}.md) "
        f'<span class="teabot-hub-version">{text(newest.get("version"))}</span>\n'
        "    { .teabot-hub-head }\n\n"
        f"    {description}\n"
        "    { .teabot-hub-description }\n\n"
        f"    by {text(author(plugin))}\n"
        "    { .teabot-hub-author }\n"
    )


def index(plugins: list[dict[str, Any]], reachable: bool) -> str:
    out = INTRO + f"\n{GENERATED}\n"
    if not reachable:
        return (
            out
            + "\n!!! warning\n\n    The hub's catalogue could not be read when this page was built. Try again later.\n"
        )
    if not plugins:
        return out + "\nNo plugins are listed yet.\n"
    cards = "\n".join(card(p) for p in plugins)
    return out + f'\n<div class="grid cards teabot-features teabot-hub" markdown>\n\n{cards}\n</div>\n'


def official(pid: str, offers: set[str] | None) -> tuple[str, str]:
    """The button and the section for using a plugin on the official Teabot, by what its list says."""
    if offers is None:
        return "", (
            f"See whether the official Teabot offers it among [its plugins]({OFFICIAL}/plugins). If it does, open "
            "its page there, sign in with Discord, choose your server and switch it on."
        )
    if pid not in offers:
        return "", "The official Teabot does not offer it yet. Its operator chooses which plugins it runs."
    link = f"{OFFICIAL}/plugins/{pid}"
    button = f"[Use it on the official Teabot]({link}){{ .md-button .md-button--primary }}\n"
    return button, (
        f"Open [its page on the official Teabot]({link}), sign in with Discord, choose your server and switch it "
        f"on. Or run this in your server:\n\n```text\n/plugins enable plugin:{pid}\n```"
    )


def page(plugin: dict[str, Any], offers: set[str] | None = None) -> str:
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
    button, on_official = official(pid, offers)
    return f"""{GENERATED}
# {text(pid)}

{text(plugin.get("description")) or "No description."}

{button}[Source]({repo}){{ .md-button }}

- **Version:** {text(newest.get("version"))}
- **Author:** {text(author(plugin))}
- **Contacts:** {text(newest.get("external_connections")) or "none given"}
- **Installs:** {others}
- **Licence:** {text(plugin.get("licence")) or "not given"}

Every version was reviewed at the commit shown. Teabot installs the newest one its own version runs.

| Version | Commit | Runs on |
|---|---|---|
{rows}

## Use it

### On the official Teabot

{on_official}

### On your own teabot

In your instance's folder:

```bash
uv run teabot hub add {pid}
```

Without uv on the machine:

```bash
docker compose run --rm uv add "{requirement}"
```

Then rebuild with `docker compose up -d --build`, and switch it on in your teabot's site or with
`/plugins enable`. See [Adding plugins](../host/adding-plugins.md).

**Back to:** [the plugin hub](index.md)
"""


def write(catalogue: dict[str, Any] | None, out: Path, offers: set[str] | None = None) -> list[str]:
    """Write the section into `out`, replacing what was there. Returns the plugin ids given pages."""
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.md"):
        old.unlink()
    plugins = listed(catalogue) if catalogue is not None else []
    (out / "index.md").write_text(index(plugins, catalogue is not None))
    for plugin in plugins:
        (out / f"{plugin['id']}.md").write_text(page(plugin, offers))
    return [p["id"] for p in plugins]


if __name__ == "__main__":
    source = sys.argv[1] if len(sys.argv) > 1 else CATALOGUE
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else OUT
    ids = write(read(source), target, offered())
    print(f"plugin hub: {len(ids)} plugins{': ' + ', '.join(ids) if ids else ''}")

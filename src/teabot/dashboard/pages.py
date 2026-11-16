"""The dashboard's pages, as HTML with no scripts. Everything a member or a plugin wrote is escaped."""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from html import escape
from typing import Any


@dataclass(frozen=True)
class PluginRow:
    """One plugin on a server's page: its id, its state there, what the hub says of it, and its settings."""

    id: str
    state: str
    description: str
    contacts: str
    settings: dict[str, Any] | None


STYLE = """
:root { --bg: #ffffff; --fg: #1d1d1f; --muted: #5f6368; --card: #f5f5f7; --accent: #5865f2; --bad: #b3261e; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #111214; --fg: #e8e8ea; --muted: #a0a3a8; --card: #1c1d20; --accent: #8891f2; --bad: #f2b8b5; }
}
body { margin: 0 auto; max-width: 52rem; padding: 2rem 1rem; background: var(--bg); color: var(--fg);
  font: 16px/1.5 system-ui, sans-serif; }
a { color: var(--accent); }
header { display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap; }
article { background: var(--card); border-radius: 12px; padding: 1rem 1.25rem; margin: 1rem 0; }
h2 small, .muted { color: var(--muted); font-weight: normal; }
button { background: var(--accent); color: #fff; border: 0; border-radius: 8px; padding: 0.4rem 0.9rem;
  font: inherit; cursor: pointer; }
button.quiet { background: transparent; color: var(--accent); border: 1px solid var(--accent); }
label { display: block; margin: 0.5rem 0 0.2rem; }
input { width: 100%; box-sizing: border-box; padding: 0.4rem; border-radius: 6px; border: 1px solid var(--muted);
  background: var(--bg); color: var(--fg); font: inherit; }
.message { border-left: 4px solid var(--accent); padding: 0.5rem 1rem; background: var(--card); }
.message.bad { border-color: var(--bad); }
form.inline { display: inline; }
"""


def page(title: str, body: str, *, signed_in: str | None = None, csrf: str = "") -> str:
    out = ""
    if signed_in is not None:
        out = (
            f'<form class="inline" method="post" action="/dashboard/logout">{_csrf(csrf)}'
            f'<span class="muted">{escape(signed_in)}</span> <button class="quiet">Sign out</button></form>'
        )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title><style>{STYLE}</style></head><body>"
        f'<header><h1><a href="/dashboard">teabot</a></h1>{out}</header>{body}</body></html>'
    )


def _csrf(token: str) -> str:
    return f'<input type="hidden" name="csrf" value="{escape(token)}">'


def message(text: str | None, *, bad: bool = False) -> str:
    if not text:
        return ""
    return f'<p class="message{" bad" if bad else ""}">{escape(text)}</p>'


def sign_in() -> str:
    body = (
        "<p>Manage teabot's plugins in the servers you run.</p>"
        '<p><a href="/dashboard/login"><button>Sign in with Discord</button></a></p>'
        '<p class="muted">teabot reads your Discord name and the servers you are in, once, and keeps nothing '
        "else.</p>"
    )
    return page("Sign in to teabot", body)


def servers(name: str, csrf: str, found: Iterable[tuple[int, str]]) -> str:
    items = "".join(f'<li><a href="/dashboard/{gid}">{escape(gname)}</a></li>' for gid, gname in found)
    body = (
        f"<h2>Your servers</h2><ul>{items}</ul>"
        if items
        else "<p>teabot is in none of the servers you manage. Add it to one, then sign in again.</p>"
    )
    return page("Your servers", body, signed_in=name, csrf=csrf)


def _setting_inputs(values: dict[str, Any]) -> str:
    fields: list[str] = []
    for key, value in values.items():
        shown = value if isinstance(value, str) else json.dumps(value)
        fields.append(
            f'<label for="s-{escape(key)}">{escape(key)}</label>'
            f'<input id="s-{escape(key)}" name="{escape(key)}" value="{escape(shown)}">'
        )
    return "".join(fields)


def _plugin(guild_id: int, row: PluginRow, csrf: str) -> str:
    base = f"/dashboard/{guild_id}/{escape(row.id)}"
    on = row.state == "enabled"
    toggle = ""
    if row.state in ("enabled", "disabled"):
        verb = "disable" if on else "enable"
        toggle = (
            f'<form class="inline" method="post" action="{base}/{verb}">{_csrf(csrf)}'
            f"<button{' class=quiet' if on else ''}>{'Turn off' if on else 'Turn on'}</button></form>"
        )
    settings = ""
    if row.settings:
        settings = (
            f'<form method="post" action="{base}/settings">{_csrf(csrf)}{_setting_inputs(row.settings)}'
            "<p><button>Save settings</button></p></form>"
        )
    contacts = f'<p class="muted">Contacts: {escape(row.contacts)}</p>' if row.contacts else ""
    return (
        f'<article id="{escape(row.id)}"><h2>{escape(row.id)} <small>{escape(row.state)}</small></h2>'
        f"<p>{escape(row.description)}</p>{contacts}{toggle}{settings}</article>"
    )


@dataclass(frozen=True)
class GuildPage:
    """A server's page: who is signed in and their form token, the server, its plugins, and a note on what the
    last change did, `bad` when it failed."""

    name: str
    csrf: str
    guild_id: int
    guild_name: str
    rows: tuple[PluginRow, ...]
    note: str = ""
    bad: bool = False


def guild(shown: GuildPage) -> str:
    body = (
        f"<h2>{escape(shown.guild_name)}</h2>{message(shown.note, bad=shown.bad)}"
        '<p class="muted">Turning a plugin on adds its commands to this server. Turning it off keeps its data and '
        "settings.</p>" + "".join(_plugin(shown.guild_id, r, shown.csrf) for r in shown.rows)
    )
    return page(shown.guild_name, body, signed_in=shown.name, csrf=shown.csrf)

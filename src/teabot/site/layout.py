"""The page every part of the site shares: the header with the instance's name, its navigation, and who is signed
in with their server picker, and the footer with the operator's pages. Everything shown is escaped."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from html import escape
from urllib.parse import quote

import teabot

DOCS = "https://teabot-dev.github.io/teabot/"


@dataclass(frozen=True)
class Viewer:
    """Who is looking. Signed out, `name` is None. Signed in: their `name`, the `csrf` token their forms send back,
    the servers they manage that the bot is in, as (id, name), and the one they chose, if any."""

    name: str | None = None
    csrf: str = ""
    servers: Sequence[tuple[int, str]] = ()
    chosen: int | None = None

    @property
    def chosen_name(self) -> str | None:
        return next((n for i, n in self.servers if i == self.chosen), None)


@dataclass(frozen=True)
class Frame:
    """What every page shows around its content: the instance's `name` and `avatar`, whether members can sign in,
    the operator's pages that exist (`privacy`, `terms`), and the `path` being shown, for returning after a sign-in
    or a server change."""

    name: str
    avatar: str | None
    sign_in: bool
    viewer: Viewer
    path: str = "/"
    legal: Sequence[str] = field(default_factory=tuple[str, ...])


def csrf_field(token: str) -> str:
    return f'<input type="hidden" name="csrf" value="{escape(token)}">'


def _account(frame: Frame) -> str:
    viewer = frame.viewer
    if viewer.name is None:
        if not frame.sign_in:
            return ""
        return f'<a class="button" href="/login?next={quote(frame.path, safe="/")}">Sign in with Discord</a>'
    options = "".join(
        f'<option value="{gid}"{" selected" if gid == viewer.chosen else ""}>{escape(name)}</option>'
        for gid, name in viewer.servers
    )
    picker = (
        '<form class="picker" method="post" action="/server">'
        f'{csrf_field(viewer.csrf)}<input type="hidden" name="next" value="{escape(frame.path)}">'
        '<label class="hidden-label" for="server">Server</label>'
        f'<select id="server" name="guild" data-autosubmit><option value="">Choose a server</option>{options}'
        '</select><noscript><button class="quiet">Choose</button></noscript></form>'
        if options
        else '<span class="muted">No servers to manage</span>'
    )
    return (
        f'<div class="account">{picker}<form method="post" action="/logout">{csrf_field(viewer.csrf)}'
        f'<button class="quiet" title="Signed in as {escape(viewer.name)}">Sign out</button></form></div>'
    )


def _footer(frame: Frame) -> str:
    links = [f'<a href="/{name}">{name.capitalize()}</a>' for name in frame.legal]
    links.append(f'<a href="{DOCS}">Runs teabot {escape(teabot.__version__)}</a>')
    return f"<footer>{' · '.join(links)}</footer>"


def page(frame: Frame, title: str, body: str, *, status_note: str = "") -> str:
    """A whole page: `title` in the tab beside the instance's name, and `body` as its content."""
    avatar = (
        f'<img src="{escape(frame.avatar)}" alt="">'
        if frame.avatar
        else '<img src="/static/logo.png" alt="">'
    )
    tab = escape(title if title == frame.name else f"{title} · {frame.name}")
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{tab}</title><link rel="icon" href="/static/favicon.png">'
        '<link rel="stylesheet" href="/static/site.css"><script src="/static/site.js" defer></script></head>'
        f'<body><header class="top"><a class="brand" href="/">{avatar}<span>{escape(frame.name)}</span></a>'
        f'<nav><a href="/plugins">Plugins</a><a href="{DOCS}use/plugins/">Help</a></nav>{_account(frame)}</header>'
        f"<main>{status_note}{body}</main>{_footer(frame)}</body></html>"
    )


def note(text: str | None, *, bad: bool = False) -> str:
    """A line saying what the last change did, read out by screen readers when it changes."""
    if not text:
        return ""
    return f'<p class="note{" bad" if bad else ""}" role="status">{escape(text)}</p>'

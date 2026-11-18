"""The site's pages: the home page, the plugin browser, a plugin's page with its switch and settings, and the
operator's own pages. Everything a member, a plugin or the hub wrote is escaped; the operator's Markdown is
rendered without raw HTML."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import escape
from typing import Any

from markdown_it import MarkdownIt

from teabot.site.info import PluginInfo
from teabot.site.layout import Frame, csrf_field, note, page

HUB_PAGES = "https://teabot-dev.github.io/teabot/hub/"


@dataclass(frozen=True)
class Here:
    """A plugin's state in the chosen server, as the member may see it: `state` is `enabled`, `disabled`, or why
    it cannot be either, such as `failed`; `settings` its config, when the member may read it."""

    state: str
    settings: Mapping[str, Any] | None = None

    @property
    def switchable(self) -> bool:
        return self.state in ("enabled", "disabled")


def _switch(frame: Frame, plugin: str, here: Here) -> str:
    viewer = frame.viewer
    if viewer.chosen is None or not here.switchable:
        return ""
    on = here.state == "enabled"
    verb = "disable" if on else "enable"
    return (
        f'<form class="switch" method="post" action="/plugins/{escape(plugin)}/{verb}" data-enhance>'
        f'{csrf_field(viewer.csrf)}<input type="hidden" name="guild" value="{viewer.chosen}">'
        f'<button class="{"on" if on else "off"}" aria-pressed="{"true" if on else "false"}">'
        f'{"On" if on else "Off"}</button><span class="result" aria-live="polite"></span></form>'
    )


def _state_line(frame: Frame, here: Here | None) -> str:
    server = frame.viewer.chosen_name
    if here is None or server is None:
        return ""
    if here.switchable:
        return ""
    return f'<p class="muted">Not available in {escape(server)}: {escape(here.state)}.</p>'


def card(frame: Frame, plugin: PluginInfo, here: Here | None) -> str:
    """A plugin in the browser: its name and version, what it does, and its switch for the chosen server."""
    switch = _switch(frame, plugin.id, here) if here is not None else ""
    return (
        f'<article class="card" id="{escape(plugin.id)}"><div class="card-head">'
        f'<a class="card-title" href="/plugins/{escape(plugin.id)}">{escape(plugin.id)}</a>'
        f'<span class="pill">{escape(plugin.version)}</span></div>'
        f'<p class="card-text">{escape(plugin.description) or "No description."}</p>'
        f'<div class="card-foot">{switch}{_state_line(frame, here)}</div></article>'
    )


def _prompt(frame: Frame) -> str:
    """What the member does next to switch plugins: sign in, or choose a server."""
    if frame.viewer.name is None:
        if not frame.sign_in:
            return '<p class="muted">Turn plugins on in Discord with <code>/plugins enable</code>.</p>'
        return '<p class="muted">Sign in with Discord to turn plugins on in the servers you manage.</p>'
    if frame.viewer.chosen is None:
        return '<p class="muted">Choose a server at the top to turn its plugins on and off.</p>'
    return f'<p class="muted">Showing <strong>{escape(frame.viewer.chosen_name or "")}</strong>.</p>'


def plugins(frame: Frame, found: Sequence[PluginInfo], here: Mapping[str, Here], status: str = "") -> str:
    cards = "".join(card(frame, p, here.get(p.id)) for p in found) or "<p>No plugins are installed.</p>"
    body = (
        f'<h1>Plugins</h1>{_prompt(frame)}<section class="cards">{cards}</section>'
        f'<p class="muted">More plugins are on the <a href="{HUB_PAGES}">plugin hub</a>. This teabot\'s operator '
        "chooses which it runs.</p>"
    )
    return page(frame, "Plugins", body, status_note=status)


def _setting_inputs(values: Mapping[str, Any]) -> str:
    fields: list[str] = []
    for key, value in values.items():
        shown = value if isinstance(value, str) else json.dumps(value)
        fields.append(
            f'<label for="s-{escape(key)}">{escape(key.replace("_", " "))}</label>'
            f'<input id="s-{escape(key)}" name="{escape(key)}" value="{escape(shown)}">'
        )
    return "".join(fields)


def _settings(frame: Frame, plugin: str, here: Here) -> str:
    if frame.viewer.chosen is None or not here.settings:
        return ""
    return (
        f"<h2>Settings in {escape(frame.viewer.chosen_name or '')}</h2>"
        f'<form class="settings" method="post" action="/plugins/{escape(plugin)}/settings" data-enhance>'
        f'{csrf_field(frame.viewer.csrf)}<input type="hidden" name="guild" value="{frame.viewer.chosen}">'
        f"{_setting_inputs(here.settings)}"
        '<p class="muted">Type numbers, and <code>true</code> or <code>false</code>, as they are, and '
        "<code>null</code> to clear one.</p>"
        '<p><button>Save settings</button> <span class="result" aria-live="polite"></span></p></form>'
    )


def plugin_page(frame: Frame, plugin: PluginInfo, here: Here | None, status: str = "") -> str:
    contacts = f"<li>Contacts: {escape(plugin.contacts)}</li>" if plugin.contacts else ""
    if "members" in plugin.reads:
        contacts += (
            "<li>Reads the member directory: every member's roles, joins and history in the server</li>"
        )
    hub = f'<li><a href="{HUB_PAGES}{escape(plugin.id)}/">On the plugin hub</a></li>' if plugin.on_hub else ""
    switch = ""
    if here is not None and here.switchable:
        switch = f'<div class="here"><span>In {escape(frame.viewer.chosen_name or "")}</span>'
        switch += f"{_switch(frame, plugin.id, here)}</div>"
    body = (
        f'<p class="crumbs"><a href="/plugins">Plugins</a></p><h1>{escape(plugin.id)} '
        f'<span class="pill">{escape(plugin.version)}</span></h1>'
        f'<p class="lead">{escape(plugin.description) or "No description."}</p>'
        f'<ul class="facts">{contacts}{hub}</ul>{_prompt(frame) if not switch else ""}{switch}'
        f"{_state_line(frame, here)}{_settings(frame, plugin.id, here) if here is not None else ''}"
    )
    return page(frame, plugin.id, body, status_note=status)


def home(frame: Frame, invite: str | None, found: Sequence[PluginInfo]) -> str:
    add = f'<a class="button" href="{escape(invite)}">Add to your server</a>' if invite else ""
    cards = "".join(card(frame, p, None) for p in found[:6])
    body = (
        f'<section class="hero"><h1>{escape(frame.name)}</h1>'
        '<p class="lead">A Discord bot run on teabot, an open-source, plugin-based bot. Choose the plugins your '
        "server needs, and turn them on and off here.</p>"
        f'<p class="actions">{add}<a class="button quiet" href="/plugins">Browse its plugins</a></p></section>'
        f'<h2>Its plugins</h2><section class="cards">{cards}</section>'
    )
    return page(frame, frame.name, body)


_MARKDOWN = MarkdownIt("commonmark", {"html": False})


def legal(frame: Frame, title: str, markdown: str) -> str:
    """One of the operator's pages, from their Markdown, with any raw HTML in it shown as text."""
    return page(frame, title, f'<article class="prose">{_MARKDOWN.render(markdown)}</article>')


def problem(frame: Frame, title: str, text: str) -> str:
    return page(frame, title, f"<h1>{escape(title)}</h1>{note(text, bad=True)}")

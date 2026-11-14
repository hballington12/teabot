"""The opening: the title, the problems teabot answers, and the agenda."""

import manimgx as m

from teabot_explainer.common import agenda, new_slide, show_title, steam, teabot
from teabot_explainer.theme import BUTTER, CLAY, LAVENDER, MUTED, SKY
from teabot_explainer.widgets import card, rule, serif, text


def title_slide(s: m.Scene) -> None:
    """The teabot mark, the name and one line on what it is."""
    s.next_section(
        "teabot",
        notes="teabot is an open-source Discord bot framework built from plugins. "
        "This walks through the architecture, hosting, plugins and one example session.",
    )
    pot = teabot(0.95).shift(m.UP * 1.25)
    wisps = steam(pot[-1].get_top(), 0.9)
    name = serif("teabot", 104, bold=True).next_to(pot, m.DOWN, buff=0.45)
    line = rule(6.0).next_to(name, m.DOWN, buff=0.25)
    sub = text("an open-source Discord bot built from plugins", 30, MUTED)
    sub.next_to(line, m.DOWN, buff=0.3)
    foot = serif("a proof-of-concept walkthrough  ·  November 2026", 22, MUTED)
    foot.to_edge(m.DOWN, buff=0.45)
    s.play(m.DrawBorderThenFill(pot), run_time=1.6)
    s.play(m.Create(wisps, lag_ratio=0.3), m.Write(name), run_time=1.4)
    s.play(m.Create(line), m.FadeIn(sub, shift=m.UP * 0.1), m.FadeIn(foot))
    s.wait(0.3)


def why_slide(s: m.Scene) -> None:
    """Four pain points, and the one-line answer."""
    new_slide(
        s,
        "Why teabot",
        notes="These come from running Tea clan events with several bots. "
        "The answer is a small core where every feature is a plugin.",
    )
    show_title(s, "Why build it", "")
    pains = [
        ("Bulk work hits rate limits", "hundreds of role edits, one request each", CLAY),
        ("Event setup repeats", "roles, channels and overwrites rebuilt per event", BUTTER),
        ("Moderation needs a trail", "and with an AI acting, which human asked", SKY),
        ("Several bots overlap", "each with its own config and permissions", LAVENDER),
    ]
    cards = m.VGroup(*[card(t, b, 6.0, 1.45, tone, 28, 20) for t, b, tone in pains]).arrange_in_grid(
        2, 2, buff=(0.35, 0.3)
    )
    cards.shift(m.UP * 0.35)
    s.play(m.LaggedStart(*[m.FadeIn(c, shift=m.UP * 0.2) for c in cards], lag_ratio=0.15))
    answer = m.VGroup(
        serif("One small core.  Every feature is a plugin.", 34, bold=True),
        text("Three front doors: Discord for people, MCP for AI agents, an API for programs.", 23),
    ).arrange(m.DOWN, buff=0.2)
    answer.next_to(cards, m.DOWN, buff=0.55)
    s.play(m.Write(answer[0]), run_time=1.2)
    s.play(m.FadeIn(answer[1], shift=m.UP * 0.1))


def agenda_slide(s: m.Scene) -> None:
    """The four chapters of the walkthrough."""
    new_slide(s, "Agenda")
    show_title(s, "The walkthrough", "")
    tabs = agenda().shift(m.DOWN * 0.1)
    s.play(m.LaggedStart(*[m.FadeIn(t, shift=m.UP * 0.2) for t in tabs], lag_ratio=0.15))
    notes = [
        "core, front doors,\nowners, edge, MCP",
        "licence, instances,\nbot identity, data, scale",
        "what they are, how they\nare made and approved",
        "add the bot, connect\nan agent, ask it",
    ]
    captions = m.VGroup(*[text(n, 19, MUTED).next_to(t, m.DOWN, buff=0.3) for n, t in zip(notes, tabs, strict=True)])
    s.play(m.FadeIn(captions, lag_ratio=0.1))

"""Reusable drawing pieces: text, cards, chips, arrows, terminals and chat mock-ups."""

from collections.abc import Sequence

import manimgx as m
import numpy as np

from teapot_explainer.theme import (
    CARD,
    CREAM,
    ESPRESSO,
    FAINT,
    INK,
    MONO,
    MUTED,
    SANS,
    SERIF,
    STONE,
    Tone,
)


def text(
    s: str,
    size: float = 26,
    color: str = INK,
    font: str = SANS,
    bold: bool = False,
) -> m.Text:
    """Text in the theme's ink, sans-serif unless told otherwise."""
    return m.Text(
        s,
        font=font,
        font_size=size,
        color=color,
        weight=m.BOLD if bold else m.NORMAL,
    )


def serif(s: str, size: float = 30, color: str = INK, bold: bool = False) -> m.Text:
    """Text in the serif face used for headings."""
    return text(s, size, color, SERIF, bold)


def mono(s: str, size: float = 20, color: str = INK) -> m.Text:
    """Text in the monospaced face used for code and commands."""
    return text(s, size, color, MONO)


def box(
    width: float,
    height: float,
    tone: Tone | None = None,
    radius: float = 0.16,
    stroke: float = 2,
) -> m.RoundedRectangle:
    """A rounded rectangle filled with a pastel tone, or the plain card colour."""
    fill = tone.fill if tone else CARD
    edge = tone.edge if tone else FAINT
    return m.RoundedRectangle(
        corner_radius=radius,
        width=width,
        height=height,
        fill_color=fill,
        fill_opacity=1,
        stroke_color=edge,
        stroke_width=stroke,
    )


def card(
    title: str,
    body: str | None = None,
    width: float = 3.0,
    height: float = 1.6,
    tone: Tone | None = None,
    title_size: float = 26,
    body_size: float = 19,
) -> m.VGroup:
    """A box with a serif title and an optional body, both centred."""
    rect = box(width, height, tone)
    head = serif(title, title_size, bold=True)
    parts: list[m.Mobject] = [head]
    if body:
        parts.append(text(body, body_size, MUTED if tone is None else INK))
    inner = m.VGroup(*parts).arrange(m.DOWN, buff=0.16)
    if inner.width > width - 0.3:
        inner.scale_to_fit_width(width - 0.3)
    inner.move_to(rect)
    return m.VGroup(rect, inner)


def chip(
    label: str,
    tone: Tone = STONE,
    size: float = 20,
    code: bool = False,
    pad: float = 0.14,
) -> m.VGroup:
    """A small rounded label that fits its text."""
    t = mono(label, size) if code else text(label, size)
    rect = box(t.width + 2 * pad + 0.1, t.height + 2 * pad, tone, radius=0.1)
    t.move_to(rect)
    return m.VGroup(rect, t)


def arrow(
    start: np.ndarray,
    end: np.ndarray,
    color: str = MUTED,
    width: float = 3,
    buff: float = 0.08,
) -> m.Arrow:
    """A thin arrow with a small tip."""
    return m.Arrow(
        start,
        end,
        buff=buff,
        color=color,
        stroke_width=width,
        tip_length=0.16,
        max_tip_length_to_length_ratio=0.3,
    )


def connect(a: m.Mobject, b: m.Mobject, color: str = MUTED) -> m.Arrow:
    """An arrow from the right edge of one mobject to the left edge of another."""
    return arrow(a.get_right(), b.get_left(), color)


def rule(width: float = 13.2, color: str = FAINT) -> m.Line:
    """A thin horizontal hairline."""
    return m.Line(m.LEFT * width / 2, m.RIGHT * width / 2, color=color, stroke_width=1.5)


def slide_title(title: str, chapter: str = "") -> m.VGroup:
    """The serif title at the top left, a hairline under it and the chapter at the right."""
    head = serif(title, 46, bold=True).to_corner(m.UL, buff=0.45)
    line = rule().next_to(head, m.DOWN, buff=0.16).set_x(0)
    parts: list[m.Mobject] = [head, line]
    if chapter:
        tag = serif(chapter, 22, MUTED).next_to(line, m.UP, buff=0.14).align_to(line, m.RIGHT)
        parts.append(tag)
    return m.VGroup(*parts)


def bullets(
    items: Sequence[str],
    size: float = 24,
    dot: str = MUTED,
    buff: float = 0.26,
) -> m.VGroup:
    """Lines of text, each after a small dot, aligned on the left."""
    rows = []
    for item in items:
        t = text(item, size)
        d = m.Dot(radius=0.05, color=dot)
        d.next_to(t, m.LEFT, buff=0.18).align_to(t[0], m.UP).shift(m.DOWN * 0.09)
        rows.append(m.VGroup(d, t))
    return m.VGroup(*rows).arrange(m.DOWN, aligned_edge=m.LEFT, buff=buff)


def terminal(lines: Sequence[tuple[str, str]], width: float = 7.0, size: float = 19) -> m.VGroup:
    """A dark terminal window. Each line is (kind, text), kind being cmd, out or note.

    The result is VGroup(background, buttons, body), and body[i] is the i-th line.
    """
    colours = {"out": CREAM, "note": "#A89C8C", "ok": "#B9D1AE", "bad": "#E3A9A2"}
    rows = []
    for kind, s in lines:
        if kind == "cmd":
            row = m.VGroup(mono("$", size, "#B9D1AE"), mono(s, size, CREAM)).arrange(m.RIGHT, buff=0.15)
        else:
            row = mono(s, size, colours[kind])
        rows.append(row)
    body = m.VGroup(*rows).arrange(m.DOWN, aligned_edge=m.LEFT, buff=0.16)
    if body.width > width - 0.6:
        body.scale_to_fit_width(width - 0.6)
    height = body.height + 0.95
    bg = m.RoundedRectangle(
        corner_radius=0.16,
        width=width,
        height=height,
        fill_color=ESPRESSO,
        fill_opacity=1,
        stroke_width=0,
    )
    buttons = m.VGroup(*[m.Dot(radius=0.06, color=c) for c in ("#D9A38B", "#E9D79F", "#A9BFA0")]).arrange(
        m.RIGHT, buff=0.12
    )
    buttons.move_to(bg.get_corner(m.UL) + m.RIGHT * 0.38 + m.DOWN * 0.24)
    body.next_to(buttons, m.DOWN, buff=0.28).align_to(buttons, m.LEFT)
    return m.VGroup(bg, buttons, body)


def code_block(source: str, size: float = 18, language: str = "python") -> m.Code:
    """Highlighted code on the espresso background."""
    return m.Code(
        code_string=source,
        language=language,
        add_line_numbers=False,
        background_config={"fill_color": ESPRESSO, "stroke_color": ESPRESSO, "buff": 0.28},
        paragraph_config={"font_size": size},
    )


def bubble(s: str, tone: Tone, size: float = 20, width: float = 5.6) -> m.VGroup:
    """A chat bubble holding a few lines of text."""
    t = text(s, size)
    if t.width > width - 0.4:
        t.scale_to_fit_width(width - 0.4)
    rect = box(t.width + 0.4, t.height + 0.34, tone, radius=0.18)
    t.move_to(rect)
    return m.VGroup(rect, t)


def tool_call(name: str, args: str, size: float = 17) -> m.VGroup:
    """An agent's tool call, drawn as a monospaced stone chip with a wrench mark."""
    head = mono(f"⚒ {name}", size, INK)
    arg = mono(args, size - 2, MUTED)
    inner = m.VGroup(head, arg).arrange(m.DOWN, aligned_edge=m.LEFT, buff=0.1)
    rect = box(inner.width + 0.36, inner.height + 0.3, STONE, radius=0.1)
    inner.move_to(rect)
    return m.VGroup(rect, inner)


def avatar(colour: str, letter: str, radius: float = 0.26) -> m.VGroup:
    """A round avatar with an initial."""
    c = m.Circle(radius=radius, fill_color=colour, fill_opacity=1, stroke_width=0)
    t = text(letter, radius * 90, CARD, bold=True).move_to(c)
    return m.VGroup(c, t)


def discord_message(
    author: str,
    colour: str,
    body: str | m.Mobject,
    size: float = 19,
    tag: str = "",
) -> m.VGroup:
    """A Discord-style message: avatar, coloured name, optional tag, then the body.

    The body is a line of text, or a mobject such as an embed.
    """
    av = avatar(colour, author[0].upper())
    name = text(author, size, colour, bold=True)
    head_parts: list[m.Mobject] = [name]
    if tag:
        head_parts.append(chip(tag, STONE, size - 3, pad=0.05))
    head = m.VGroup(*head_parts).arrange(m.RIGHT, buff=0.12)
    msg = text(body, size) if isinstance(body, str) else body
    col = m.VGroup(head, msg).arrange(m.DOWN, aligned_edge=m.LEFT, buff=0.1)
    av.next_to(col, m.LEFT, buff=0.18).align_to(col, m.UP)
    return m.VGroup(av, col)


def embed(title: str, body: str, edge: str, width: float = 5.2, size: float = 18) -> m.VGroup:
    """A Discord embed: a coloured bar on the left, a bold title and a body."""
    t = text(title, size + 2, bold=True)
    b = text(body, size)
    inner = m.VGroup(t, b).arrange(m.DOWN, aligned_edge=m.LEFT, buff=0.12)
    if inner.width > width - 0.5:
        inner.scale_to_fit_width(width - 0.5)
    bg = box(width, inner.height + 0.4, STONE, radius=0.08, stroke=0)
    bg.set_fill(CARD)
    bar = m.Rectangle(width=0.07, height=bg.height, fill_color=edge, fill_opacity=1, stroke_width=0)
    bar.align_to(bg, m.LEFT).align_to(bg, m.UP)
    inner.align_to(bg, m.LEFT).shift(m.RIGHT * 0.28).set_y(bg.get_y())
    return m.VGroup(bg, bar, inner)


def tick(colour: str, size: float = 0.22) -> m.VMobject:
    """A check mark."""
    return m.VMobject(color=colour, stroke_width=5).set_points_as_corners(
        [m.LEFT * size, m.DOWN * size * 0.8 + m.LEFT * size * 0.15, m.UR * size]
    )


def cross(colour: str, size: float = 0.2) -> m.VGroup:
    """An X mark."""
    a = m.Line(m.UL * size, m.DR * size, color=colour, stroke_width=5)
    b = m.Line(m.UR * size, m.DL * size, color=colour, stroke_width=5)
    return m.VGroup(a, b)

"""Pieces every chapter uses: starting a slide, the chapter agenda and the teapot mark."""

import manimgx as m
import numpy as np

from teapot_explainer.theme import BUTTER, CLAY, INK, MUTED, SAGE, SKY, Tone
from teapot_explainer.widgets import box, serif, slide_title, text

CHAPTERS: list[tuple[str, str, Tone]] = [
    ("I", "Architecture", SAGE),
    ("II", "Hosting", SKY),
    ("III", "Plugins", BUTTER),
    ("IV", "A day in the life", CLAY),
]


def clear(s: m.Scene, run_time: float = 0.5) -> None:
    """Fade out everything on screen."""
    if s.mobjects:
        s.play(*[m.FadeOut(x) for x in s.mobjects], run_time=run_time)


def new_slide(s: m.Scene, name: str, notes: str = "") -> None:
    """Begin a slide: a new section, then the previous slide fades away."""
    s.next_section(name, notes=notes)
    clear(s)


def show_title(s: m.Scene, title: str, chapter: str) -> m.VGroup:
    """Write the slide's title and return it."""
    head = slide_title(title, chapter)
    s.play(m.FadeIn(head, shift=m.DOWN * 0.15), run_time=0.6)
    return head


def agenda(active: int | None = None) -> m.VGroup:
    """The four chapters as tabs, with one optionally highlighted."""
    tabs = []
    for i, (num, name, tone) in enumerate(CHAPTERS):
        rect = box(2.9, 1.9, tone if active in (None, i) else None)
        n = serif(num, 40, INK if active in (None, i) else MUTED, bold=True)
        t = serif(name, 26, INK if active in (None, i) else MUTED)
        inner = m.VGroup(n, t).arrange(m.DOWN, buff=0.2).move_to(rect)
        tabs.append(m.VGroup(rect, inner))
    return m.VGroup(*tabs).arrange(m.RIGHT, buff=0.3)


def chapter_divider(s: m.Scene, index: int, blurb: str) -> None:
    """A slide that opens a chapter: the agenda with this chapter lifted."""
    num, name, _tone = CHAPTERS[index]
    new_slide(s, f"Chapter {num}: {name}")
    tabs = agenda(index).shift(m.UP * 0.4)
    s.play(m.LaggedStart(*[m.FadeIn(t, shift=m.UP * 0.2) for t in tabs], lag_ratio=0.12))
    s.play(tabs[index].animate.shift(m.UP * 0.35).scale(1.08))
    line = text(blurb, 26, MUTED).next_to(tabs, m.DOWN, buff=0.9)
    s.play(m.FadeIn(line, shift=m.UP * 0.1))


def teapot(scale: float = 1.0) -> m.VGroup:
    """A simple teapot drawn from shapes: body, lid, knob, spout and handle."""
    edge = CLAY.edge
    body = m.Ellipse(width=2.6, height=1.9, fill_color=CLAY.fill, fill_opacity=1)
    body.set_stroke(edge, 4)
    lid = m.Arc(radius=0.62, start_angle=0, angle=np.pi, fill_color=SAGE.fill, fill_opacity=1)
    lid.set_stroke(edge, 4).next_to(body, m.UP, buff=-0.12)
    knob = m.Circle(radius=0.13, fill_color=SAGE.edge, fill_opacity=1).set_stroke(edge, 3)
    knob.next_to(lid, m.UP, buff=-0.03)
    spout = m.VMobject(fill_color=CLAY.fill, fill_opacity=1).set_stroke(edge, 4)
    spout.set_points_smoothly(
        [
            [-1.1, -0.35, 0],
            [-1.55, -0.05, 0],
            [-1.85, 0.55, 0],
            [-2.05, 0.7, 0],
            [-1.75, 0.6, 0],
            [-1.4, 0.15, 0],
            [-1.05, 0.15, 0],
        ]
    )
    handle = m.Arc(radius=0.6, start_angle=-np.pi * 0.55, angle=np.pi * 1.1, color=edge)
    handle.set_stroke(edge, 9).move_to(body.get_right() + m.RIGHT * 0.18)
    pot = m.VGroup(spout, handle, body, lid, knob)
    return pot.scale(scale)


def steam(anchor: np.ndarray, scale: float = 1.0) -> m.VGroup:
    """Three wavy lines of steam rising from a point."""
    wisps = []
    for dx in (-0.32, 0.0, 0.32):
        w = m.FunctionGraph(
            lambda y: 0.09 * np.sin(4.2 * y),
            x_range=[0, 1.0],
            color=MUTED,
        ).set_stroke(MUTED, 3, opacity=0.7)
        w.rotate(np.pi / 2).move_to(anchor + m.RIGHT * dx * scale + m.UP * 0.55 * scale)
        wisps.append(w.scale(scale))
    return m.VGroup(*wisps)

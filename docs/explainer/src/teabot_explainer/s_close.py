"""The close: where the build stands, the open decisions, and the end card."""

import manimgx as m

from teabot_explainer.common import new_slide, show_title, steam, teabot
from teabot_explainer.theme import BUTTER, CLAY, FAINT, LAVENDER, MUTED, SAGE, SKY, STONE
from teabot_explainer.widgets import card, chip, rule, serif, text

MILESTONES = [
    ("M1", "Skeleton", "workspace,\nPostgres, locks,\nwork queue"),
    ("M2", "Actions", "SDK, call path,\naudit, first\nplugin"),
    ("M3", "Lifecycles", "admin plugin,\ncommand sync,\npurges"),
    ("M4", "Tokens, MCP", "tokens, MCP\nserver, service\nAPI"),
    ("M5", "Tea instance", "droplet, Caddy,\nbackups"),
    ("M6", "Plan, apply", "diffs, confirm,\nqueued applies"),
    ("M7", "Release", "SDK 1.0,\ntemplate, repo\ngoes public"),
]


DONE = {"M1", "M2", "M3"}  # milestones finished on main


def chapter(s: m.Scene) -> None:
    """Run the closing slides."""
    roadmap_slide(s)
    end_slide(s)


def roadmap_slide(s: m.Scene) -> None:
    """Seven milestones on a line, the current position, and the open decisions."""
    new_slide(
        s,
        "Where we are",
        notes="Milestones 1 to 3 and every spike are done. In milestone 4, tokens and the "
        "admin lookups are in. The MCP server (WP4.3) and the service API (WP4.4) are next.",
    )
    show_title(s, "Where we are", "")
    xs = [-5.7 + i * 1.95 for i in range(7)]
    line = m.Line([xs[0] - 0.8, 1.1, 0], [xs[-1] + 0.6, 1.1, 0], color=FAINT, stroke_width=4)
    tones = [SAGE, SAGE, SKY, LAVENDER, BUTTER, CLAY, STONE]
    stops = m.VGroup()
    for (code, name, detail), x, tone in zip(MILESTONES, xs, tones, strict=True):
        dot = m.Circle(radius=0.2, fill_color=tone.fill, fill_opacity=1, stroke_color=tone.edge, stroke_width=3)
        dot.move_to([x, 1.1, 0])
        if code in DONE:
            dot.set_fill(tone.edge)
        head = serif(code, 22, tone.edge, bold=True).next_to(dot, m.UP, buff=0.15)
        label = serif(name, 19, bold=True).next_to(dot, m.DOWN, buff=0.2)
        body = text(detail, 16, MUTED).next_to(label, m.DOWN, buff=0.12)
        stops.add(m.VGroup(dot, head, label, body))
    s.play(m.Create(line))
    s.play(m.LaggedStart(*[m.FadeIn(st, shift=m.UP * 0.1) for st in stops], lag_ratio=0.12))
    here = m.Triangle(color=CLAY.edge, fill_color=CLAY.edge, fill_opacity=1).scale(0.12).rotate(m.PI)
    here.move_to([xs[3], 1.95, 0])
    here_label = text("now: MCP server next", 17, CLAY.edge, bold=True)
    here_label.next_to(here, m.UP, buff=0.1)
    s.play(m.FadeIn(here, shift=m.DOWN * 0.2), m.FadeIn(here_label))
    open_head = serif("Open decisions", 26, bold=True)
    opens = m.VGroup(
        card("The licence", "Apache-2.0, MIT or BSD-2-Clause", 3.9, 1.1, BUTTER, 21, 16),
        card(
            "When OAuth lands",
            "only if claude.ai or the desktop\napp need access early",
            3.9,
            1.1,
            LAVENDER,
            21,
            16,
        ),
        card("The plugin hub", "its format, once a second\nplugin author exists", 3.9, 1.1, SKY, 21, 16),
    ).arrange(m.RIGHT, buff=0.3)
    group = m.VGroup(open_head, opens).arrange(m.DOWN, buff=0.25).move_to([0, -2.55, 0])
    s.play(m.FadeIn(group, lag_ratio=0.1))


def end_slide(s: m.Scene) -> None:
    """The teabot again, and an invitation to talk."""
    new_slide(s, "Thanks", notes="Questions, and what to build first.")
    pot = teabot(0.8).shift(m.UP * 1.0)
    wisps = steam(pot[-1].get_top(), 0.75)
    head = serif("Questions and ideas welcome", 54, bold=True).next_to(pot, m.DOWN, buff=0.5)
    line = rule(6.0).next_to(head, m.DOWN, buff=0.25)
    docs = (
        m.VGroup(
            chip("README.md  decisions D1 to D50", STONE, 18),
            chip("docs/plan.md  the build plan", STONE, 18),
            chip("docs/implementation.md  the work order", STONE, 18),
        )
        .arrange(m.RIGHT, buff=0.25)
        .next_to(line, m.DOWN, buff=0.4)
    )
    s.play(m.FadeIn(pot), m.Create(wisps, lag_ratio=0.3))
    s.play(m.Write(head), m.Create(line))
    s.play(m.FadeIn(docs, lag_ratio=0.15))

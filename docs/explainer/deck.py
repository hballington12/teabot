"""The teabot walkthrough as one ManimGX scene: each `next_section` is a slide.

Present it with `uv run manimgx present deck.py --pdf`.
"""

import manimgx as m

from teabot_explainer import s_architecture, s_close, s_hosting, s_intro, s_lifecycle, s_plugins
from teabot_explainer.theme import apply_config

apply_config()


class TeabotWalkthrough(m.Scene):
    """Title, agenda, the four chapters and the close."""

    def construct(self) -> None:
        s_intro.title_slide(self)
        s_intro.why_slide(self)
        s_intro.agenda_slide(self)
        s_architecture.chapter(self)
        s_hosting.chapter(self)
        s_plugins.chapter(self)
        s_lifecycle.chapter(self)
        s_close.chapter(self)

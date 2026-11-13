"""Colours and type for the explainer: warm parchment, ink and pastel accents."""

from dataclasses import dataclass

import manimgx as m

PAPER = "#F5F0E6"  # page background, a parchment off-white
CARD = "#FBF8F2"  # card fill, a shade lighter than the page
INK = "#3E3631"  # main text, a warm charcoal brown
MUTED = "#8A7F74"  # secondary text and rules
FAINT = "#D9D0C3"  # hairlines, inactive parts
ESPRESSO = "#3A322C"  # terminal and code background
CREAM = "#EFE6D6"  # text on espresso


@dataclass(frozen=True)
class Tone:
    """A pastel fill with a deeper stroke of the same hue."""

    fill: str
    edge: str


SAGE = Tone("#DCE5D3", "#7E9A76")
CLAY = Tone("#F1D9CC", "#B9775F")
SKY = Tone("#D7E2EA", "#6F8FA8")
BUTTER = Tone("#F2E7C4", "#B3954A")
LAVENDER = Tone("#E2DBEA", "#8F7FA8")
ROSE = Tone("#F0D6D3", "#B5726C")
STONE = Tone("#E9E3D9", "#9C8F80")

GOOD = SAGE.edge
BAD = ROSE.edge

SERIF = "Libertinus Serif"
SANS = "Noto Sans"
MONO = "DejaVu Sans Mono"


def apply_config() -> None:
    """Set the page colour on the global config, before any scene is built."""
    m.config.background_color = PAPER

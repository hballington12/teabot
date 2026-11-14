"""Write out/artifact/index.html: the deck's own player, filled with ManimGX's slide timings.

ManimGX's presenter page seeks the video in place, which fails on hosts that ignore HTTP
Range requests (the film plays on and jumps back to the start) and shows nothing on phones
until the video preloads. `player.html` loads the film into memory first and has on-screen
controls. This takes the slide list ManimGX wrote and puts it into that player.
Run it after `manimgx present`.
"""

import json
import re
from pathlib import Path

HERE = Path(__file__).parent
SOURCE = HERE / "out" / "teabot-walkthrough.html"
TEMPLATE = HERE / "player.html"
TARGET = HERE / "out" / "artifact" / "index.html"


def main() -> None:
    match = re.search(r"^const deck = (\{.*\});", SOURCE.read_text(encoding="utf-8"), re.MULTILINE)
    if match is None:
        raise SystemExit(f"no slide list found in {SOURCE}")
    deck = json.loads(match.group(1))
    page = TEMPLATE.read_text(encoding="utf-8").replace("/*DECK*/null", json.dumps(deck))
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(page, encoding="utf-8")
    print(f"{TARGET}: {len(deck['sections'])} slides")


if __name__ == "__main__":
    main()

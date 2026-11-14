# teabot explainer deck

An animated slide deck that explains teabot to a collaborator, made with [ManimGX](https://github.com/academa-labs/manimgx). It covers the architecture, hosting, plugins and an example agent session, in 34 slides and about three minutes of animation.

## Run it

- `uv sync` sets up the environment. ManimGX comes from the shared clone's wheel in `~/opt/manimgx/dist` (see `pyproject.toml`). Delete the `[tool.uv.sources]` entry to use ManimGX 0.1.1 from PyPI instead.
- `uv run manimgx present deck.py -o out/teabot-walkthrough.mp4 --pdf` renders the video, writes the slide page and a PDF handout into `out/`, and opens the page.
    - → or a click goes to the next slide, ← goes back, F is full screen.
    - Shift+P opens the presenter view with the speaker notes.
    - To share it, send `out/teabot-walkthrough.html` and `out/teabot-walkthrough.mp4` together, or the PDF.
- `uv run manimgx inspect deck.py -o tmp/deck.png` writes storyboards and checks every slide's layout without rendering video.
- `uv run python artifact_page.py` fills `player.html` with the slide timings ManimGX wrote and saves it as `out/artifact/index.html`. That page is the one published as a claude.ai Artifact, with the video beside it.
    - ManimGX's own page seeks the video while it streams. On a host that ignores HTTP Range requests the film then plays past each slide and jumps back to the start. Phones also show nothing until the video preloads.
    - `player.html` loads the whole film into memory before it starts, so seeking works on any host. It has a Start screen and on-screen Back and Next buttons, and taps on the left or right half of the slide go back or on. Browsers without per-frame video callbacks fall back to checking every repaint.
- `uv run python tests/player_check.py` checks that player in Chrome against a server without Range support, at desktop size, at phone size with taps, and with per-frame callbacks removed. Each slide must stop on the first frame of the next one. It saves a screenshot per viewport width in `tmp/`.

## Layout

- `deck.py`: the one scene, `TeabotWalkthrough`, which runs the chapters in order.
- `player.html`: the web player for the published deck. `artifact_page.py` fills in its slide list.
- `tests/player_check.py`: the browser check of that player.
- `src/teabot_explainer/`:
    - `theme.py`: the parchment and pastel palette, and the fonts (Libertinus Serif, Noto Sans, DejaVu Sans Mono, all shipped with ManimGX).
    - `widgets.py`: cards, chips, arrows, terminals, code blocks, chat bubbles and Discord mock-ups.
    - `common.py`: starting a slide, the chapter agenda and the teabot drawing.
    - `s_intro.py`, `s_architecture.py`, `s_hosting.py`, `s_plugins.py`, `s_lifecycle.py`, `s_close.py`: one module per chapter, one function per slide.
- `out/` and `tmp/` hold renders and storyboards, and git ignores both.

## Keeping it true

- Every slide is drawn from the design in the repository's `README.md` and `docs/plan.md`. When a decision changes there, change the matching slide and render again.
- `roles_bulk_remove` in chapter IV stands in for a future roles plugin, and the speaker notes say so.

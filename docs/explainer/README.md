# teapot explainer deck

An animated slide deck that explains teapot to a collaborator, made with [ManimGX](https://github.com/academa-labs/manimgx). It covers the architecture, hosting, plugins and an example agent session, in 34 slides and about three minutes of animation.

## Run it

- `uv sync` sets up the environment. ManimGX comes from the shared clone's wheel in `~/opt/manimgx/dist` (see `pyproject.toml`). Delete the `[tool.uv.sources]` entry to use ManimGX 0.1.1 from PyPI instead.
- `uv run manimgx present deck.py -o out/teapot-walkthrough.mp4 --pdf` renders the video, writes the slide page and a PDF handout into `out/`, and opens the page.
    - → or a click goes to the next slide, ← goes back, F is full screen.
    - Shift+P opens the presenter view with the speaker notes.
    - To share it, send `out/teapot-walkthrough.html` and `out/teapot-walkthrough.mp4` together, or the PDF.
- `uv run manimgx inspect deck.py -o tmp/deck.png` writes storyboards and checks every slide's layout without rendering video.
- `uv run python artifact_page.py` turns the rendered page into `out/artifact/index.html`, the copy published as a claude.ai Artifact beside the video.

## Layout

- `deck.py`: the one scene, `TeapotWalkthrough`, which runs the chapters in order.
- `src/teapot_explainer/`:
    - `theme.py`: the parchment and pastel palette, and the fonts (Libertinus Serif, Noto Sans, DejaVu Sans Mono, all shipped with ManimGX).
    - `widgets.py`: cards, chips, arrows, terminals, code blocks, chat bubbles and Discord mock-ups.
    - `common.py`: starting a slide, the chapter agenda and the teapot drawing.
    - `s_intro.py`, `s_architecture.py`, `s_hosting.py`, `s_plugins.py`, `s_lifecycle.py`, `s_close.py`: one module per chapter, one function per slide.
- `out/` and `tmp/` hold renders and storyboards, and git ignores both.

## Keeping it true

- Every slide is drawn from the design in the repository's `README.md` and `docs/plan.md`. When a decision changes there, change the matching slide and render again.
- `roles_bulk_remove` in chapter IV stands in for a future roles plugin, and the speaker notes say so.

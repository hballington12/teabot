# Scripts

- `check.sh`: applies ruff's fixes and formatting, then runs ruff, pyright, import-linter and pytest, as CI does. Run it before every push. Arguments go to pytest.
- `release/`: the release workflow's steps, which `tests/release/` tests. `check.py` refuses a tag that the versions, the changelog or the template do not match, `pin.py` pins the plugin to its core, `template.py` builds the locked template archive, and `notes.py` prints the release notes. They share `release_lib.py`.
- `quality.sh`: the ub-mode gates: crapper fails above CRAP 10, dryer at 0.8 similarity, and mutator on the files git sees as changed, or on the paths given. Needs crapper, dryer and mutator on PATH.
- `docs/hub.py`: writes the docs' plugin hub section, `docs/hub/`, from the hub's catalogue. Run it before building the docs; CI and the docs workflow do.
- `docs/brand.py`: makes the site's and README's images from the art in `brand/`: the home page's mascots, and Teabot's icon at 512, 256 and 64 px. Run it with `uv run scripts/docs/brand.py` after changing the art.

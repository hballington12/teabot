# Scripts

- `check.sh`: applies ruff's fixes and formatting, then runs ruff, pyright, import-linter and pytest, as CI does. Run it before every push. Arguments go to pytest.
- `release/`: the release workflow's steps, which `tests/release/` tests. `check.py` refuses a tag that the versions, the changelog or the template do not match, `pin.py` pins the plugin to its core, `template.py` builds the locked template archive, and `notes.py` prints the release notes. They share `release_lib.py`.
- `quality.sh`: the ub-mode gates: crapper fails above CRAP 10, dryer at 0.8 similarity, and mutator on the files git sees as changed, or on the paths given. Needs crapper, dryer and mutator on PATH.

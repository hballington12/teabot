# Scripts

- `check.sh`: applies ruff's fixes and formatting, then runs ruff, pyright, import-linter and pytest, as CI does. Run it before every push. Arguments go to pytest.
- `quality.sh`: the ub-mode gates: crapper fails above CRAP 10, dryer at 0.8 similarity, and mutator on the files git sees as changed, or on the paths given. Needs crapper, dryer and mutator on PATH.

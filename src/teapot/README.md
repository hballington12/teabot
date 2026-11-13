# teapot package

- `__init__.py`: the package version.
- `__main__.py`: `python -m teapot`, the same CLI as the `teapot` script.
- `cli/`: the `teapot` command line (D34).
- `settings.py`: instance settings from `TEAPOT_*` variables and `teapot.env`. `template/teapot.env.example` lists them all.
- `logs.py`: logging setup, text in dev mode and JSON lines in production.
- `sdk/`: the public plugin API (D45). Plugins import only from here.
- `py.typed`: marks the package as typed for plugin authors.

The rest of the layout in `docs/plan.md` arrives work package by work package.

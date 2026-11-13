# teapot package

- `__init__.py`: the package version.
- `__main__.py`: `python -m teapot`, the same CLI as the `teapot` script.
- `cli/`: the `teapot` command line (D34).
- `sdk/`: the public plugin API (D45). Plugins import only from here.
- `py.typed`: marks the package as typed for plugin authors.

The rest of the layout in `docs/plan.md` arrives work package by work package.

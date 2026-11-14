# teapot.sdk

- The public plugin API (D45). Plugins import from `teapot.sdk` and nothing else in teapot.
- `__init__.py` lists every public name, by area. Only those names are public; the modules here are internal.
- `actions.py`: `ActionSpec`, `ActionContext`, `Actor`, `Risk`, `Surface` and `ActionError`.
- `plugin.py`: `Manifest`, `Plugin`, `Registrar`, and the job types.
- `db.py`: the database protocols a plugin sees (D30).
- `fields.py`: the `*Ref`, `LongText` and `UntrustedText` field types (D23, D29).
- `inputs.py`: which input field types each front door can offer (D29).
- `plans.py`: `Diff` and `DiffEntry`, what a destructive action's plan returns (D21).
- `ids.py`: the plugin id pattern and the reserved ids (D46).
- `deprecation.py`: keeping an old name or form working, with a warning, until the next major release.
- `tests/sdk/` checks that every public name is documented and that the import-linter contracts cover every
  internal module.

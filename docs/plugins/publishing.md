# Publishing a plugin

At the end of this page, other people can install your plugin on their own teabot.

A plugin in your instance's `plugins/` folder is yours alone. To share it, publish it as a Python package, on PyPI or in a git repository. Operators then add it with one command, as in [Adding plugins](../host/adding-plugins.md).

## 1. Move it to its own repository

Copy `plugins/<id>/` into a repository of its own. It is already a complete package: `pyproject.toml`, the code, the migrations, the tests and the README.

## 2. Depend on a range of teabot

In `pyproject.toml`, depend on the teabot versions your plugin works with. The scaffold writes the range of the teabot it was made with:

```toml title="pyproject.toml"
[project]
dependencies = ["teabot>=1.0,<2"]
```

teabot keeps plugins working across a major version, so `<2` is safe. Raise the lower bound when you use something new; the [release notes](../host/changelog.md) say what each release added for plugins.

## 3. List what it contacts

The README's **External connections** says every server outside Discord your plugin contacts, or "none". Operators read it before they install a plugin, and `teabot check` refuses a README without it.

```markdown title="README.md"
- External connections: api.example.org, to look up player scores. The same hosts go in `Plugin(..., hosts=["api.example.org"])`, which `ctx.http` keeps to.
```

## 4. Check it

In the plugin's repository, with your instance's Postgres running:

```bash
uv run pytest
uv run teabot check .
```

The tests run `teabot check` too. It refuses imports from teabot's internals, reading the clock directly, `SET` in SQL, and a README without its "External connections".

## 5. Publish it

Give it a version in `pyproject.toml`, then build and upload it with uv:

```bash
uv build
uv publish
```

`uv publish` needs a [PyPI token](https://pypi.org/help/#apitoken), or [trusted publishing](https://docs.pypi.org/trusted-publishers/) from GitHub Actions. Name the package `teabot-<id>`, so operators can find it.

To publish from git instead, tag a release, and operators add it by its URL and tag.

## Keeping it working

- Never edit a migration you have released. Add a new numbered file for each change.
- Change settings only in ways older settings still fit: add new ones with defaults, and keep old names working.
- The snapshot test catches a renamed option or job argument, which would break queued jobs and the commands members know.

A curated plugin hub, where teabot's maintainers review plugins before listing them, is planned.

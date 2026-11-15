# Publishing a plugin

At the end of this page, other people can install your plugin on their own teabot, from the plugin hub or from its own repository.

A plugin in your instance's `plugins/` folder is yours alone. To share it, publish it as a Python package, on PyPI or in a git repository. Operators then add it with one command, as in [Adding plugins](../host/adding-plugins.md).

## 1. Move it to its own repository

Copy `plugins/<id>/` into a repository of its own. It is already a complete package: `pyproject.toml`, the code, the migrations, the tests and the README.

Add a `LICENSE` file, such as the MIT licence, which says others may use it. The plugin hub lists open-source plugins only.

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

## 6. List it on the hub

The [plugin hub](https://teabot-dev.github.io/plugin-hub/) lists plugins that teabot's maintainers have reviewed, and every instance can install them with `teabot hub add`. To list yours, add one file to the hub's repository, in a pull request:

```text title="plugins/raffles"
repository=https://github.com/you/teabot-raffles.git
commit=9db374fc205c5aae1f99bd5fd127266076f40ec8
```

- The file is named for the plugin's id, and the commit is the full hash of the commit to list.
- The pull request's checks install the plugin at that commit, run `teabot check` and its tests, and post a report. Fix anything they find in your repository, then change `commit=` in the same pull request.
- Every package your plugin installs beyond teabot's own must be on the hub's `allowed-dependencies.txt`. To add one, open a pull request to that file first, saying what your plugin needs it for. Fewer is better: prefer what teabot already brings, such as `ctx.http` for web requests and pydantic for models.
- A maintainer reads the code at that commit and merges it. The plugin then appears on the hub's page within minutes.
- To release an update, change `commit=` in a new pull request. The report links the changes since the listed commit, which is what the maintainer reviews.

The hub's [README](https://github.com/teabot-dev/plugin-hub) has the steps in full, and what review looks for.

## Keeping it working

- Never edit a migration you have released. Add a new numbered file for each change.
- Change settings only in ways older settings still fit: add new ones with defaults, and keep old names working.
- The snapshot test catches a renamed option or job argument, which would break queued jobs and the commands members know.


# Contributing to teabot

## Before you start

- The design is in the [README](README.md), as numbered decisions such as (D21). A change that goes against a decision starts as an issue proposing to change it.
- Report a bug as an issue with the steps that show it. Report a security problem as [SECURITY.md](SECURITY.md) describes.
- A plugin for your own instance needs nobody's approval (D44); [docs/plugin-authoring.md](docs/plugin-authoring.md) covers writing one. First-party plugins in this repository follow its review checklist.

## Setting up

```
git clone https://github.com/hballington12/teabot.git
cd teabot
uv sync
docker compose -f template/compose.yaml up -d --wait postgres
```

- uv runs everything: every command is `uv run ...`.
- The tests use that Postgres on `127.0.0.1:55432`. Each test gets its own database and roles, and drops them after.

## Checks

- `scripts/check.sh` runs what CI runs: ruff's formatting and lint, pyright in strict mode, the import-linter contracts and pytest. Run it before every push.
- `scripts/quality.sh` runs the stricter gates: CRAP under 10, no near-duplicate code, and no surviving mutants in the files you changed. It needs crapper, dryer and mutator on your PATH.

## Making a change

- One change per pull request, with tests that fail without it.
- Keep functions short and their nesting shallow, and modularise one that passes 150 lines. Each directory's README is a bullet list of what is in it.
- A commit message has a short title, then says why, what changed, and how it was proven.
- `teabot.sdk` follows semantic versioning (D45). An addition is a minor release. A breaking change needs a major release, and the old form first keeps working with a warning from `teabot.sdk.deprecation` for at least one minor release.
- A released migration never changes. Add a new numbered file instead.
- Add a line to [CHANGELOG.md](CHANGELOG.md) under **Unreleased**, with a **For operators** note when upgrading needs a manual step.

## Releasing

For the maintainers. `teabot` and `teabot-announcements` are released together under one version.

1. In one commit on `main`, set that version in `pyproject.toml` and `plugins/announcements/pyproject.toml`, and rename the changelog's **Unreleased** heading to `## <version> - <date>`.
2. Tag it and push the tag: `git tag v<version>` and `git push origin v<version>`.
3. The release workflow checks the versions, the changelog and the template against the tag, publishes both packages to PyPI, and attaches the locked template to a GitHub release with the changelog section as its notes.
4. Set the versions to the next `.dev0` and add a new **Unreleased** heading.

A new major version also moves the template's ranges, such as `teabot>=2.0,<3`.

## Licence and conduct

- Contributions are under the [MIT licence](LICENSE), as the rest of the project is.
- Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).

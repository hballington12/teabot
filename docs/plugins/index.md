# Your first plugin

A **plugin** adds commands to teabot. It is a small Python package: functions that become slash commands and AI assistant tools, a database table or two of its own, and tests. At the end of this page, you have made one, tested it, and run it in Discord. It takes about ten minutes.

!!! note "Before you start"

    You need:

    - A teabot instance from the [quick start](../host/index.md), with its folder open in a terminal.
    - [uv](https://docs.astral.sh/uv/getting-started/installation/) on your machine, so your editor and the tests can use the plugin's code:

        ```bash
        curl -LsSf https://astral.sh/uv/install.sh | sh
        ```

    - Python you can read. A little SQL helps.

## 1. Make the plugin

In your instance's folder:

```bash
uv run teabot new-plugin polls
```

```text
created plugins/polls
next: uv run --package teabot-polls pytest plugins/polls
then rebuild the bot with docker compose up -d --build, and run /plugins enable plugin:polls
```

It writes one package, with an example action called `hello`:

```text
plugins/polls/
    pyproject.toml                      the package, and how teabot finds it
    README.md                           what it does, and every server it contacts
    src/teabot_polls/
        __init__.py                     the plugin
        migrations/0001_greetings.sql   its table
        py.typed                        tells type checkers the package has types
    tests/
        test_polls.py                   its tests
        test_polls_snapshot.py          a record of its commands, kept in snapshot.json
```

## 2. Run its tests

```bash
uv run --package teabot-polls pytest plugins/polls
```

```text
3 passed in 1.02s
```

The tests run against your instance's Postgres, which `setup.sh` started. Each test gets a database of its own, and drops it afterwards. The first run also writes `tests/snapshot.json`.

## 3. Read the plugin

This is all of `src/teabot_polls/__init__.py`:

```python title="plugins/polls/src/teabot_polls/__init__.py"
--8<-- "tests/docs/scaffold/polls/src/teabot_polls/__init__.py"
```

- `plugin = Plugin("polls")` is the plugin. Its id, `polls`, is the command's name: `/polls`.
- `@plugin.action()` makes `hello` an action: the slash command `/polls hello`, and the AI assistant tool `polls_hello`.
- Its parameters after `ctx` are the command's options. The docstring's first line describes the command, and its `Args:` section describes each option.
- `ctx` is the call: which server (`ctx.guild`), who asked (`ctx.actor`), and the plugin's database (`ctx.db`).
- It returns a `Greeted`, and `render` is the reply the member sees.

The tests call the action the way Discord would, permissions and all:

```python title="plugins/polls/tests/test_polls.py"
--8<-- "tests/docs/scaffold/polls/tests/test_polls.py"
```

## 4. Change it

Make the reply your own. In `__init__.py`, change `render`:

```python
    def render(self) -> str:
        return f"Hi there! That is hello number {self.times}."
```

Run the tests again. They still pass, since they check what the action returns, not how it is shown.

## 5. See it in Discord

Rebuild the bot with the plugin in it, then turn the plugin on in your server:

```bash
docker compose up -d --build
```

```text
/plugins enable plugin:polls
/polls hello
```

teabot replies `Hi there! That is hello number 1.`

## Next

- The [tutorial](tutorial.md) grows `polls` into a real plugin: options, votes, a job that posts the results, and a confirmed delete.
- The [reference](reference.md) has every part of a plugin in one page.

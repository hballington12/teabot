"""`teabot check`: the review checklist a plugin's code can be checked against (D45).

- Plugin code imports only `teabot.sdk`; its tests may also import `teabot.testing`.
- Plugin SQL never runs `SET`, `RESET` or `set_config`, which could change the role or the server it acts for.
- Times come from `ctx.now` and SQL's `now()`, which tests can move, never from `datetime.now()`,
  `CURRENT_TIMESTAMP` and the like, which they cannot.
- The plugin's README lists its external connections (D12).

The harness runs these when it loads a plugin, and `teabot check` runs them from the command line. A problem
fails a test or the command; it never stops a running bot.
"""

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ALLOWED_IN_CODE = ("teabot.sdk",)
ALLOWED_IN_TESTS = ("teabot.sdk", "teabot.testing")
SET_STATEMENT = re.compile(
    r"^(SET\s+(SESSION\s+|LOCAL\s+)?(ROLE\b|SESSION\s+AUTHORIZATION\b|[A-Za-z_][\w.]*\s*(=|TO\b))"
    r"|RESET\s+(ALL|ROLE|[A-Za-z_][\w.]*)\s*$)",
    re.IGNORECASE,
)
SET_CONFIG = re.compile(r"\bset_config\s*\(", re.IGNORECASE)
SQL_CLOCKS = re.compile(
    r"\b(CURRENT_TIMESTAMP|LOCALTIMESTAMP|CURRENT_TIME|LOCALTIME|CURRENT_DATE|transaction_timestamp|"
    r"statement_timestamp|clock_timestamp|timeofday)\b",
    re.IGNORECASE,
)
PYTHON_CLOCKS = {
    ("datetime", "now"),
    ("datetime", "utcnow"),
    ("datetime", "today"),
    ("date", "today"),
    ("time", "time"),
}
COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


@dataclass(frozen=True)
class Problem:
    """One thing to change, with where it is."""

    path: Path
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


def check_package(package: Path) -> list[Problem]:
    """Every problem in a plugin's package directory, its migrations and its README."""
    problems: list[Problem] = []
    for path in sorted(package.rglob("*.py")):
        in_tests = "tests" in path.relative_to(package).parts
        problems += _check_python(path, ALLOWED_IN_TESTS if in_tests else ALLOWED_IN_CODE)
    for path in sorted(package.rglob("*.sql")):
        problems += _check_sql(path, path.read_text(), 1)
    problems += _check_readme(package)
    return problems


def check_project(project: Path) -> list[Problem]:
    """Every problem in a plugin project: its packages under `src/`, or the directory itself, and its tests."""
    packages = [p.parent for p in sorted(project.glob("src/*/__init__.py"))] or [project]
    problems = [problem for package in packages for problem in check_package(package)]
    tests = project / "tests"
    if tests.is_dir():
        for path in sorted(tests.rglob("*.py")):
            problems += _check_python(path, ALLOWED_IN_TESTS)
    return problems


def _check_python(path: Path, allowed: tuple[str, ...]) -> list[Problem]:
    tree = ast.parse(path.read_text(), filename=str(path))
    problems: list[Problem] = []
    for node in ast.walk(tree):
        line: int = getattr(node, "lineno", 1)
        for module in _imported(node):
            if (module == "teabot" or module.startswith("teabot.")) and not module.startswith(allowed):
                problems.append(
                    Problem(path, line, f"imports {module}; plugins import only {' and '.join(allowed)}")
                )
        if isinstance(node, ast.Call) and _clock_call(node):
            problems.append(
                Problem(path, node.lineno, "reads the clock directly, which tests cannot move; use ctx.now")
            )
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            problems += _check_sql(path, node.value, node.lineno, strict=False)
    return problems


def _imported(node: ast.AST) -> Iterator[str]:
    if isinstance(node, ast.Import):
        yield from (alias.name for alias in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
        if node.module == "teabot":
            yield from (f"teabot.{alias.name}" for alias in node.names)
        else:
            yield node.module


def _clock_call(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    owner = func.value
    name = owner.attr if isinstance(owner, ast.Attribute) else owner.id if isinstance(owner, ast.Name) else ""
    return (name, func.attr) in PYTHON_CLOCKS


def _check_sql(path: Path, text: str, first_line: int, *, strict: bool = True) -> list[Problem]:
    """SQL problems in `text`. In a Python string, which may be prose, only clear SQL counts."""
    problems: list[Problem] = []
    for statement, offset in _statements(text):
        line = first_line + offset
        if SET_STATEMENT.match(statement) or SET_CONFIG.search(statement):
            problems.append(
                Problem(
                    path,
                    line,
                    "changes a setting with SET, RESET or set_config, which plugin SQL must not do",
                )
            )
        clock = SQL_CLOCKS.search(statement)
        if clock is not None and (strict or _looks_like_sql(statement)):
            problems.append(Problem(path, line, f"uses {clock.group(1)}, which tests cannot move; use now()"))
    return problems


def _statements(text: str) -> Iterator[tuple[str, int]]:
    """Each statement in `text`, without comments, with the line it starts on, counted from 0."""
    cleaned = COMMENTS.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    position = 0
    for piece in cleaned.split(";"):
        stripped = piece.strip()
        if stripped:
            yield stripped, cleaned.count("\n", 0, position + len(piece) - len(piece.lstrip()))
        position += len(piece) + 1


def _looks_like_sql(statement: str) -> bool:
    return (
        re.match(r"(SELECT|INSERT|UPDATE|DELETE|WITH|CREATE|ALTER)\b", statement, re.IGNORECASE) is not None
    )


def _check_readme(package: Path) -> list[Problem]:
    for directory in (package, *package.parents):
        readme = directory / "README.md"
        if readme.is_file():
            if "External connections" in readme.read_text():
                return []
            return [
                Problem(
                    readme, 1, 'has no "External connections" section listing the hosts the plugin contacts'
                )
            ]
        if (directory / "pyproject.toml").is_file():
            break
    return [Problem(package, 1, 'the plugin has no README.md with an "External connections" section')]

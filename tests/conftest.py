"""The core's tests use the same Postgres fixtures teabot ships for plugin authors (D45), loaded with
`-p teabot.testing.fixtures` in pyproject.toml so the plugin tests share them."""

import os
from pathlib import Path
from typing import Any

import pytest

from teabot.db.naming import Naming


@pytest.fixture
def env_file(
    tmp_path: Path, owner_kwargs: dict[str, Any], naming: Naming, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """An env file pointing the CLI at this test's database and role prefix, with nothing else set."""
    for name in list(os.environ):
        if name.startswith("TEABOT_"):
            monkeypatch.delenv(name)
    env = tmp_path / "teabot.env"
    env.write_text(
        f"TEABOT_DB_HOST={owner_kwargs['host']}\n"
        f"TEABOT_DB_PORT={owner_kwargs['port']}\n"
        f"TEABOT_DB_NAME={owner_kwargs['database']}\n"
        f"TEABOT_DB_OWNER_USER={owner_kwargs['user']}\n"
        f"TEABOT_DB_OWNER_PASSWORD={owner_kwargs['password']}\n"
        f"TEABOT_DB_ROLE_PREFIX={naming.prefix}\n"
    )
    return env

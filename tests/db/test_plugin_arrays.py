"""Plugins can use array columns and array parameters.

asyncpg looks up an array type the first time it meets one, and before that lookup it calls
`set_config('jit', 'off', false)` whenever the server supports JIT. teabot revokes `set_config` from plugin roles
(D9), so the lookup used to fail with "permission denied for function set_config".
"""

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from teabot.sdk import ActionContext, ActionSpec, Manifest, Registrar, Risk
from teabot.testing import PluginHarness


class Tag(BaseModel):
    text: str


class Tagged(BaseModel):
    matching: int


async def tag(ctx: ActionContext, data: Tag) -> Tagged:
    async with ctx.db.transaction() as tx:
        await tx.execute(
            "INSERT INTO posts (guild_id, member_ids, tags) VALUES ($1, $2, $3)",
            ctx.guild.id,
            [1, 2, 3],
            [data.text, "other"],
        )
        matching: int = await tx.fetchval(
            "SELECT count(*) FROM posts WHERE guild_id = $1 AND $2 = ANY(tags) AND member_ids && $3",
            ctx.guild.id,
            data.text,
            [3, 4],
        )
    return Tagged(matching=matching)


class Arrays:
    def __init__(self, migrations: Path) -> None:
        self.manifest = Manifest("arrays", "1.0", migrations=migrations)

    def setup(self, registrar: Registrar) -> None:
        registrar.action(ActionSpec("arrays.tag", "Tag a post", Tag, Tagged, Risk.WRITE, tag))


@pytest.fixture
def arrays(tmp_path: Path) -> Arrays:
    directory = tmp_path / "arrays"
    directory.mkdir()
    (directory / "0001_posts.sql").write_text(
        "CREATE TABLE posts (guild_id bigint NOT NULL, member_ids bigint[] NOT NULL, tags text[] NOT NULL);"
    )
    return Arrays(directory)


async def test_a_plugin_reads_and_writes_array_columns_and_parameters(
    teabot_harness: Any, arrays: Arrays
) -> None:
    harness: PluginHarness = await teabot_harness(arrays)
    assert await harness.invoke("arrays.tag", {"text": "bingo"}) == Tagged(matching=1)

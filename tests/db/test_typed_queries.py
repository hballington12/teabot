"""Typed queries: `fetch(Model, sql)`, `fetchrow(Model, sql)` and `fetchval(int, sql)` check each row they return."""

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from teabot.db.pool import Pools


class Entry(BaseModel):
    member: int
    note: str


async def seeded(pools: Pools, admin: Any) -> Any:
    await admin.execute("CREATE TABLE typed_entries (member bigint, note text)")
    await admin.execute("INSERT INTO typed_entries VALUES (1, 'a'), (2, 'b')")
    await admin.execute('GRANT SELECT ON typed_entries TO "' + pools.naming.app_role + '"')
    return pools.core_db()


async def test_fetch_checks_each_row_into_a_model(pools: Pools, admin: Any) -> None:
    db = await seeded(pools, admin)
    rows = await db.fetch(Entry, "SELECT member, note FROM typed_entries ORDER BY member")
    assert rows == [Entry(member=1, note="a"), Entry(member=2, note="b")]


async def test_fetchrow_gives_a_model_or_none(pools: Pools, admin: Any) -> None:
    db = await seeded(pools, admin)
    assert await db.fetchrow(Entry, "SELECT member, note FROM typed_entries WHERE member = $1", 2) == Entry(
        member=2, note="b"
    )
    assert await db.fetchrow(Entry, "SELECT member, note FROM typed_entries WHERE member = $1", 9) is None


async def test_fetchval_and_single_column_rows_take_a_plain_type(pools: Pools, admin: Any) -> None:
    db = await seeded(pools, admin)
    assert await db.fetchval(int, "SELECT count(*) FROM typed_entries") == 2
    assert await db.fetch(int, "SELECT member FROM typed_entries ORDER BY member") == [1, 2]


async def test_a_value_that_does_not_fit_is_refused(pools: Pools, admin: Any) -> None:
    db = await seeded(pools, admin)
    with pytest.raises(ValidationError):
        await db.fetchval(int, "SELECT note FROM typed_entries LIMIT 1")


async def test_several_columns_need_a_model(pools: Pools, admin: Any) -> None:
    db = await seeded(pools, admin)
    with pytest.raises(TypeError, match="give a model for several columns"):
        await db.fetch(int, "SELECT member, note FROM typed_entries")


async def test_untyped_queries_still_return_rows(pools: Pools, admin: Any) -> None:
    db = await seeded(pools, admin)
    rows = await db.fetch("SELECT member FROM typed_entries ORDER BY member")
    assert [r["member"] for r in rows] == [1, 2]

"""A typed store for each server (D10): pydantic records by key, with no SQL and no migrations.

```python
class Tally(BaseModel):
    count: int = 0

async def bump(ctx: Ctx, member: Member) -> str:
    tallies = ctx.store(Tally)
    tally = await tallies.get(member) or Tally()
    tally.count += 1
    await tallies.put(member, tally)
```

Records live in the plugin's own schema, in its `teabot_store` table, held to the server like every plugin table.
A key is text, or a `Member` or `User`, which is kept as their ID so deleting a member's data finds it. A record
is checked through its model on every read, so a model may change only in ways the stored records still validate,
as config does: new fields with defaults, aliases for renames, `extra="ignore"` for removals.
"""

from typing import Any

from pydantic import BaseModel

from teabot.sdk.db import Db

TABLE = "teabot_store"
GET = f"SELECT value FROM {TABLE} WHERE guild_id = $1 AND kind = $2 AND key = $3"
PUT = f"""
INSERT INTO {TABLE} (guild_id, kind, key, member_id, value) VALUES ($1, $2, $3, $4, $5::jsonb)
ON CONFLICT (guild_id, kind, key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
"""
DELETE = f"DELETE FROM {TABLE} WHERE guild_id = $1 AND kind = $2 AND key = $3"
ALL = f"SELECT key, value FROM {TABLE} WHERE guild_id = $1 AND kind = $2 ORDER BY key LIMIT $3"
LIMIT = 1000

type Key = str | Any
"""Text, or a `Member` or `User`."""


def _key(key: Key) -> tuple[str, int | None]:
    """The stored key, and the member's ID when the key is a member."""
    if isinstance(key, str):
        if key.startswith("member:"):
            raise ValueError("Keys starting with member: are kept for members; pass the Member itself")
        return key, None
    member_id = int(key.id)
    return f"member:{member_id}", member_id


class Store[M: BaseModel]:
    """One kind of record in one server's store: `ctx.store(Model)`. `kind` names it, the model's name unless
    `ctx.store(Model, kind="...")` says otherwise, so renaming the class keeps its records under the old kind."""

    def __init__(self, db: Db, guild_id: int, model: type[M], kind: str) -> None:
        self._db = db
        self._guild_id = guild_id
        self.model = model
        self.kind = kind

    async def get(self, key: Key) -> M | None:
        """The record under `key`, or None."""
        stored, _ = _key(key)
        value = await self._db.fetchval(GET, self._guild_id, self.kind, stored)
        return None if value is None else self.model.model_validate_json(value)

    async def put(self, key: Key, record: M) -> None:
        """Keep `record` under `key`, replacing what was there."""
        stored, member_id = _key(key)
        await self._db.execute(PUT, self._guild_id, self.kind, stored, member_id, record.model_dump_json())

    async def delete(self, key: Key) -> bool:
        """Remove the record under `key`. Returns whether there was one."""
        stored, _ = _key(key)
        return await self._db.execute(DELETE, self._guild_id, self.kind, stored) == "DELETE 1"

    async def all(self, *, limit: int = LIMIT) -> dict[str, M]:
        """Every record of this kind in the server, by key, up to `limit`. A member's key reads `member:<id>`."""
        rows = await self._db.fetch(ALL, self._guild_id, self.kind, limit)
        return {row["key"]: self.model.model_validate_json(row["value"]) for row in rows}

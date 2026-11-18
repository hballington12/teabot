"""`ctx.members` (D55): the member directory for a plugin that declares `reads=["members"]`, in one server only.

Core code runs every query, through the core's own connection and the same query builder as `admin.members`, so no
plugin setting can widen it to another server.
"""

from datetime import UTC, datetime

from teabot.core.directory import state as states
from teabot.core.directory.labels import LabelService
from teabot.core.directory.query import Criteria, count_sql, criteria, where_all
from teabot.core.directory.rows import join_method
from teabot.db.pool import Database
from teabot.sdk.members import FIND_LIMIT, DirectoryMember, DirectoryUnavailable, MemberFilter

FIND_COLUMNS = "user_id, name, global_name, nickname, role_ids, joined_at, bot, join_source"


class GuildMembers:
    """One server's directory, as `ctx.members`."""

    def __init__(self, db: Database, guild_id: int, labels: LabelService | None = None) -> None:
        self.db = db
        self.guild_id = guild_id
        self.labels = labels

    async def _criteria(self, filters: tuple[MemberFilter, ...]) -> list[Criteria]:
        return [await resolved(f, self.guild_id, self.labels) for f in filters or (MemberFilter(),)]

    async def _ready(self) -> None:
        state = await states.load(self.db, self.guild_id)
        if state.off:
            raise DirectoryUnavailable(
                "The member directory is off in this server, which has more members than this teabot allows."
            )
        if not state.backfilled:
            raise DirectoryUnavailable("The member directory is still taking its first copy of this server.")

    async def count(self, *filters: MemberFilter) -> int:
        await self._ready()
        w = where_all(self.guild_id, await self._criteria(filters), datetime.now(UTC))
        return int(await self.db.fetchval(count_sql(w), *w.args))

    async def find(
        self, *filters: MemberFilter, after: int = 0, limit: int = FIND_LIMIT
    ) -> list[DirectoryMember]:
        await self._ready()
        w = where_all(self.guild_id, await self._criteria(filters), datetime.now(UTC))
        w.add("user_id > {}", after)
        size = max(1, min(limit, FIND_LIMIT))
        sql = f"SELECT {FIND_COLUMNS} FROM core.members WHERE {w.sql()} ORDER BY user_id LIMIT {size}"
        return [
            DirectoryMember(
                user_id=r["user_id"],
                name=r["name"],
                display_name=r["nickname"] or r["global_name"] or r["name"],
                nickname=r["nickname"],
                role_ids=tuple(r["role_ids"]),
                joined_at=r["joined_at"],
                bot=r["bot"],
                join_method=join_method(r["join_source"]),
            )
            for r in await self.db.fetch(sql, *w.args)
        ]


async def resolved(
    model: MemberFilter, guild_id: int, labels: LabelService | None, **extra: object
) -> Criteria:
    """The query builder's criteria for a filter in one server, with whether its labels count there now."""
    live = (
        model.labels_from is not None
        and labels is not None
        and await labels.live(guild_id, model.labels_from)
    )
    return criteria(model, labels_live=live, **extra)

"""What a plugin sees of the database (D30): one statement per call, and an explicit `tx` for transactions.

The core implements these protocols; plugins never import its classes.
"""

from collections.abc import Iterable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, overload

import discord

from teabot.sdk.components import Button, Select
from teabot.sdk.guild import TextChannel


class Row(Protocol):
    """One result row: values by column name."""

    def __getitem__(self, key: str, /) -> Any: ...


class Queries(Protocol):
    """Running SQL. Arguments are passed as `$1`, `$2` and so on, never formatted into the query.

    Give a result type first and each row is checked into it: `fetch(Running, sql, gid)` returns `list[Running]`,
    and `fetchval(int, sql, gid)` an `int`. A model takes a row's columns by name; any other type, such as `int`,
    takes a row's only column.
    """

    async def execute(self, query: str, *args: Any) -> str:
        """Run one statement and return its status, such as `INSERT 0 1`."""
        ...

    @overload
    async def fetch(self, query: str, /, *args: Any) -> Sequence[Row]: ...
    @overload
    async def fetch[T](self, result: type[T], query: str, /, *args: Any) -> list[T]: ...
    async def fetch(self, *args: Any) -> Any:
        """Every row the query returns."""
        ...

    @overload
    async def fetchrow(self, query: str, /, *args: Any) -> Row | None: ...
    @overload
    async def fetchrow[T](self, result: type[T], query: str, /, *args: Any) -> T | None: ...
    async def fetchrow(self, *args: Any) -> Any:
        """The first row, or None when there is none."""
        ...

    @overload
    async def fetchval(self, query: str, /, *args: Any) -> Any: ...
    @overload
    async def fetchval[T](self, result: type[T], query: str, /, *args: Any) -> T: ...
    async def fetchval(self, *args: Any) -> Any:
        """The first column of the first row, or None when there is none; ask for `int | None` when there may
        be none, since `int` refuses None."""
        ...


@dataclass(frozen=True)
class Bound:
    """One of a plugin's jobs with its arguments fixed, as `job.bind(...)` makes it.

    - `handler` is the job's name, and `payload` its arguments as JSON values.
    - `key` is the handler and its arguments, so scheduling the same bound job again moves the pending one.
    """

    handler: str
    payload: Mapping[str, Any]
    key: str


class Scheduler(Protocol):
    """Queues jobs for later, through the core's queue (D31)."""

    @overload
    async def schedule(self, job: Bound, /, *, at: datetime | None = None, key: str | None = None) -> int: ...
    @overload
    async def schedule(
        self, job: str, /, *, run_at: datetime | None = None, payload: Mapping[str, Any] | None = None
    ) -> int: ...
    async def schedule(self, job: Any, /, **options: Any) -> int:
        """Queue one of the plugin's jobs for this server, now or at `at`, and return its id.

        A bound job, `draw.bind(giveaway=gid)`, carries its own key, which `key=` can replace: scheduling a key
        that has a pending job moves that job instead of adding another. The form `schedule("draw",
        run_at=..., payload=...)` names the job by its handler and has no key.
        """
        ...

    async def unschedule(self, job: Bound | str, /) -> bool:
        """Cancel the pending job with this bound job's key, or this key. Returns whether there was one."""
        ...


@dataclass(frozen=True)
class Post:
    """A message queued with `tx.send`. Store its `id` to edit or delete it later: `Post(row["post_id"])`."""

    id: int


class Outbox(Protocol):
    """Posting that commits with the transaction's writes, so a rollback posts nothing and a commit posts once.

    The core posts within a few seconds of the commit, and retries if Discord is down. A post goes out once: a
    retry within Discord's few-minute window for repeats is dropped, and only a retry after a long outage or a
    restart could post it twice. Nobody is pinged unless named in `ping`. Use `channel.send` instead when the
    action needs the message straight away, such as to reply with its link.
    """

    async def send(
        self,
        channel: TextChannel | int,
        content: str | None = None,
        *,
        embed: discord.Embed | None = None,
        ping: Iterable[int] = (),
        buttons: Sequence[Button] = (),
        select: Select | None = None,
    ) -> Post:
        """Queue a message for `channel`, a channel or its ID. Raises `ValueError` for buttons or a menu Discord
        would refuse."""
        ...

    async def edit(
        self,
        post: Post | int,
        content: str | None = None,
        *,
        embed: discord.Embed | None = None,
        ping: Iterable[int] = (),
        buttons: Sequence[Button] = (),
        select: Select | None = None,
    ) -> None:
        """Replace what a queued post shows: what is given is what it shows. Editing before it has gone out
        changes what goes out."""
        ...

    async def delete(self, post: Post | int) -> None:
        """Delete a queued post, or stop it going out. Deleting one already gone does nothing."""
        ...


class Tx(Queries, Scheduler, Outbox, Protocol):
    """Inside `async with db.transaction() as tx:`. A job queued or a post sent here commits with the writes."""


class Db(Queries, Protocol):
    """The plugin's own tables. Each call outside a transaction is one statement on its own (D30)."""

    def transaction(self) -> AbstractAsyncContextManager[Tx]:
        """Open a transaction: `async with ctx.db.transaction() as tx:`. It commits when the block ends."""
        ...

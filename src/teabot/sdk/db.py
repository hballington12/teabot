"""What a plugin sees of the database (D30): one statement per call, and an explicit `tx` for transactions.

The core implements these protocols; plugins never import its classes.
"""

from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any, Protocol


class Row(Protocol):
    """One result row: values by column name."""

    def __getitem__(self, key: str, /) -> Any: ...


class Queries(Protocol):
    """Running SQL. Arguments are passed as `$1`, `$2` and so on, never formatted into the query."""

    async def execute(self, query: str, *args: Any) -> str:
        """Run one statement and return its status, such as `INSERT 0 1`."""
        ...

    async def fetch(self, query: str, *args: Any) -> Sequence[Row]:
        """Every row the query returns."""
        ...

    async def fetchrow(self, query: str, *args: Any) -> Row | None:
        """The first row, or None when there is none."""
        ...

    async def fetchval(self, query: str, *args: Any) -> Any:
        """The first column of the first row, or None when there is none."""
        ...


class Scheduler(Protocol):
    """Queues jobs for later, through the core's queue (D31)."""

    async def schedule(
        self,
        handler: str,
        *,
        run_at: datetime | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> int:
        """Queue the plugin's job `handler` for this server, now or at `run_at`, and return its id."""
        ...


class Tx(Queries, Scheduler, Protocol):
    """Inside `async with db.transaction() as tx:`. A job queued here commits with the writes."""


class Db(Queries, Protocol):
    """The plugin's own tables. Each call outside a transaction is one statement on its own (D30)."""

    def transaction(self) -> AbstractAsyncContextManager[Tx]:
        """Open a transaction: `async with ctx.db.transaction() as tx:`. It commits when the block ends."""
        ...

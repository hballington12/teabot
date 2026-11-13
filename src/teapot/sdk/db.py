"""What a plugin sees of the database (D30): one statement per call, and an explicit `tx` for transactions.

The core implements these protocols; plugins never import its classes.
"""

from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any, Protocol

type Row = Mapping[str, Any]


class Queries(Protocol):
    async def execute(self, query: str, *args: Any) -> str:
        """Run one statement and return its status, such as `INSERT 0 1`."""
        ...

    async def fetch(self, query: str, *args: Any) -> Sequence[Row]: ...

    async def fetchrow(self, query: str, *args: Any) -> Row | None: ...

    async def fetchval(self, query: str, *args: Any) -> Any: ...


class Scheduler(Protocol):
    async def schedule(
        self,
        handler: str,
        *,
        run_at: datetime | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> int:
        """Queue one of this plugin's jobs for this server (D31). Returns the job id."""
        ...


class Tx(Queries, Scheduler, Protocol):
    """Inside `async with db.transaction() as tx:`. A job queued here commits with the writes."""


class Db(Queries, Protocol):
    def transaction(self) -> AbstractAsyncContextManager[Tx]: ...

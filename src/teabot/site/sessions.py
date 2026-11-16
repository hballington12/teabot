"""Site sign-ins, kept in `core.web_sessions`. The browser holds a random token; the table holds its hash."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from teabot.db.pool import Database

LIFETIME = timedelta(days=7)
CREATE = """
INSERT INTO core.web_sessions (token_hash, user_id, name, guild_ids, csrf, expires_at)
VALUES ($1, $2, $3, $4, $5, now() + $6::interval)
"""
FIND = """
SELECT user_id, name, guild_ids, csrf FROM core.web_sessions WHERE token_hash = $1 AND expires_at > now()
"""
END = "DELETE FROM core.web_sessions WHERE token_hash = $1"
PRUNE = "DELETE FROM core.web_sessions WHERE expires_at <= now()"


def _hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


@dataclass(frozen=True)
class Session:
    """A signed-in member: their Discord ID and name, the servers they manage, and the token every form sends
    back to prove it came from the site."""

    user_id: int
    name: str
    guild_ids: frozenset[int]
    csrf: str


class Sessions:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def start(self, user_id: int, name: str, guild_ids: list[int]) -> str:
        """Sign a member in. Returns the token for their cookie."""
        token = secrets.token_urlsafe(32)
        await self.db.execute(
            CREATE, _hash(token), user_id, name, guild_ids, secrets.token_urlsafe(24), LIFETIME
        )
        return token

    async def find(self, token: str | None) -> Session | None:
        """The live session a cookie holds, or None."""
        if not token:
            return None
        row = await self.db.fetchrow(FIND, _hash(token))
        if row is None:
            return None
        return Session(
            int(row["user_id"]), str(row["name"]), frozenset(int(g) for g in row["guild_ids"]), row["csrf"]
        )

    async def end(self, token: str | None) -> None:
        if token:
            await self.db.execute(END, _hash(token))

    async def prune(self) -> str:
        """Delete expired sign-ins; the daily maintenance runs this."""
        return await self.db.execute(PRUNE)

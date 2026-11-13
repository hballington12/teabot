"""Tokens (D16, D17, D20).

A token is `teapot_<id>_<secret>`, after GitHub's format: the id finds the row directly and the prefix lets
secret scanners spot a leak. The secret is long and random, so a SHA-256 hash is enough to store, and it is
compared in constant time. `last used` is written at most once a minute per token and process, so a busy
token does not write on every call.
"""

import hashlib
import hmac
import secrets
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from teapot.core.registry import TokenLimits
from teapot.db.pool import Database
from teapot.sdk import Risk

PREFIX = "teapot"
LAST_USED_EVERY = 60.0
DEFAULT_LIFETIME = timedelta(days=30)

INSERT = """
INSERT INTO core.tokens (id, secret_hash, guild_id, user_id, label, max_risk, allowed_actions, expires_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, now() + $8::interval) RETURNING expires_at
"""
FIND = """
SELECT secret_hash, guild_id, user_id, max_risk, allowed_actions, expires_at <= now() AS expired,
       revoked_at IS NOT NULL AS revoked
FROM core.tokens WHERE id = $1
"""
TOUCH = "UPDATE core.tokens SET last_used = now() WHERE id = $1"
REVOKE = "UPDATE core.tokens SET revoked_at = now() WHERE id = $1 AND guild_id = $2 AND revoked_at IS NULL"
LIST = """
SELECT id, user_id, label, max_risk, allowed_actions, expires_at, last_used FROM core.tokens
WHERE guild_id = $1 AND ($2::bigint IS NULL OR user_id = $2) AND revoked_at IS NULL AND expires_at > now()
ORDER BY created_at
"""


class TokenRefused(Exception):
    """The token is malformed, unknown, wrong, expired or revoked. The message never echoes the secret."""


@dataclass(frozen=True)
class Grant:
    """Who a checked token acts as, where, and within what limits."""

    token_id: str
    guild_id: int
    user_id: int
    limits: TokenLimits


@dataclass(frozen=True)
class NewToken:
    """What a member asks for: new tokens default to `write` and 30 days (D17)."""

    label: str
    max_risk: Risk = Risk.WRITE
    lifetime: timedelta = DEFAULT_LIFETIME
    allowed: Iterable[str] = ()


@dataclass(frozen=True)
class Issued:
    token: str
    token_id: str
    expires_at: datetime


@dataclass(frozen=True)
class TokenRow:
    token_id: str
    user_id: int
    label: str
    max_risk: Risk
    allowed: tuple[str, ...]
    expires_at: datetime
    last_used: datetime | None


def parse(presented: str) -> tuple[str, str]:
    """The id and secret of `teapot_<id>_<secret>`. The secret may itself hold underscores."""
    prefix, _, rest = presented.partition("_")
    token_id, _, secret = rest.partition("_")
    if prefix != PREFIX or not token_id or not secret:
        raise TokenRefused("not a teapot token")
    return token_id, secret


def digest(secret: str) -> bytes:
    return hashlib.sha256(secret.encode()).digest()


class Tokens:
    def __init__(self, db: Database, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.db = db
        self.clock = clock
        self._touched: dict[str, float] = {}

    async def issue(self, guild_id: int, user_id: int, new: NewToken) -> Issued:
        token_id, secret = secrets.token_hex(6), secrets.token_urlsafe(32)
        allowed = sorted(set(new.allowed))
        row = (
            token_id,
            digest(secret),
            guild_id,
            user_id,
            new.label,
            int(new.max_risk),
            allowed,
            new.lifetime,
        )
        expires_at: datetime = await self.db.fetchval(INSERT, *row)
        return Issued(f"{PREFIX}_{token_id}_{secret}", token_id, expires_at)

    async def check(self, presented: str) -> Grant:
        token_id, secret = parse(presented)
        row = await self.db.fetchrow(FIND, token_id)
        if row is None or not hmac.compare_digest(bytes(row["secret_hash"]), digest(secret)):
            raise TokenRefused("unknown token")
        if row["revoked"]:
            raise TokenRefused("this token was revoked")
        if row["expired"]:
            raise TokenRefused("this token has expired")
        await self._touch(token_id)
        limits = TokenLimits(Risk(row["max_risk"]), frozenset(row["allowed_actions"]))
        return Grant(token_id, row["guild_id"], row["user_id"], limits)

    async def _touch(self, token_id: str) -> None:
        now = self.clock()
        last = self._touched.get(token_id)
        if last is not None and now - last < LAST_USED_EVERY:
            return
        self._touched[token_id] = now
        await self.db.execute(TOUCH, token_id)

    async def revoke(self, token_id: str, guild_id: int) -> bool:
        """Revoke a token of this server. False when there is no such live token here."""
        return await self.db.execute(REVOKE, token_id, guild_id) == "UPDATE 1"

    async def find(self, token_id: str, guild_id: int) -> TokenRow | None:
        rows = [r for r in await self.list(guild_id, None) if r.token_id == token_id]
        return rows[0] if rows else None

    async def list(self, guild_id: int, user_id: int | None) -> list[TokenRow]:
        """The live tokens in a server, of one member or of everyone."""
        return [
            TokenRow(
                r["id"],
                r["user_id"],
                r["label"],
                Risk(r["max_risk"]),
                tuple(r["allowed_actions"]),
                r["expires_at"],
                r["last_used"],
            )
            for r in await self.db.fetch(LIST, guild_id, user_id)
        ]

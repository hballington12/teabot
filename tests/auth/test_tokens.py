"""Tokens (WP4.1, D16, D17, D20): issued once, stored hashed, checked in constant time, throttled `last used`."""

from collections.abc import Callable
from datetime import timedelta

import pytest

from teapot.auth.tokens import Grant, NewToken, TokenRefused, Tokens, parse
from teapot.core.registry import TokenLimits
from teapot.db.migrate import migrate
from teapot.db.naming import Naming
from teapot.db.pool import Pools
from teapot.db.types import Conn
from teapot.sdk import Risk

GUILD, MEMBER = 1001, 2001


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
async def tokens(admin: Conn, naming: Naming, pools: Pools, clock: Clock) -> Tokens:
    await migrate(admin, naming, [])
    return Tokens(pools.core_db(), clock=clock)


async def test_an_issued_token_checks_as_its_member_server_and_limits(tokens: Tokens) -> None:
    issued = await tokens.issue(
        GUILD, MEMBER, NewToken("claude", max_risk=Risk.READ, allowed=["alpha.count"])
    )
    assert issued.token.startswith(f"teapot_{issued.token_id}_")
    assert await tokens.check(issued.token) == Grant(
        issued.token_id, GUILD, MEMBER, TokenLimits(Risk.READ, frozenset({"alpha.count"}))
    )


async def test_only_the_hash_of_the_secret_is_stored(tokens: Tokens, admin: Conn) -> None:
    issued = await tokens.issue(GUILD, MEMBER, NewToken("claude"))
    stored = await admin.fetchval("SELECT secret_hash FROM core.tokens WHERE id = $1", issued.token_id)
    assert parse(issued.token)[1].encode() not in stored and len(stored) == 32


def last_character_changed(token: str) -> str:
    return token[:-1] + ("A" if token[-1] != "A" else "B")


def lengthened(token: str) -> str:
    return token + "x"


@pytest.mark.parametrize("mangle", [last_character_changed, lengthened])
async def test_a_wrong_secret_is_refused(tokens: Tokens, mangle: Callable[[str], str]) -> None:
    issued = await tokens.issue(GUILD, MEMBER, NewToken("claude"))
    with pytest.raises(TokenRefused):
        await tokens.check(mangle(issued.token))


@pytest.mark.parametrize("presented", ["", "teapot", "teapot_abc", "teapot__x", "github_abc_def", "Bearer x"])
async def test_a_malformed_token_is_refused_as_not_a_teapot_token(tokens: Tokens, presented: str) -> None:
    with pytest.raises(TokenRefused, match="not a teapot token"):
        await tokens.check(presented)


async def test_a_well_formed_token_nobody_issued_is_unknown(tokens: Tokens) -> None:
    with pytest.raises(TokenRefused, match="unknown token"):
        await tokens.check("teapot_nosuchid_secret")


async def test_an_expired_token_is_refused(tokens: Tokens, admin: Conn) -> None:
    issued = await tokens.issue(GUILD, MEMBER, NewToken("claude", lifetime=timedelta(days=1)))
    await admin.execute(
        "UPDATE core.tokens SET expires_at = now() - interval '1 second' WHERE id = $1", issued.token_id
    )
    with pytest.raises(TokenRefused, match="expired"):
        await tokens.check(issued.token)


async def test_a_revoked_token_is_refused(tokens: Tokens) -> None:
    issued = await tokens.issue(GUILD, MEMBER, NewToken("claude"))
    assert await tokens.revoke(issued.token_id, GUILD) is True
    with pytest.raises(TokenRefused, match="revoked"):
        await tokens.check(issued.token)
    assert await tokens.revoke(issued.token_id, GUILD) is False


async def test_a_token_is_revoked_only_from_its_own_server(tokens: Tokens) -> None:
    issued = await tokens.issue(GUILD, MEMBER, NewToken("claude"))
    assert await tokens.revoke(issued.token_id, 9999) is False
    assert (await tokens.check(issued.token)).guild_id == GUILD


async def test_last_used_is_written_at_most_once_a_minute(tokens: Tokens, admin: Conn, clock: Clock) -> None:
    issued = await tokens.issue(GUILD, MEMBER, NewToken("claude"))

    async def last_used() -> object:
        return await admin.fetchval("SELECT last_used FROM core.tokens WHERE id = $1", issued.token_id)

    await tokens.check(issued.token)
    first = await last_used()
    assert first is not None
    clock.now += 59
    await admin.execute(
        "UPDATE core.tokens SET last_used = now() - interval '1 hour' WHERE id = $1", issued.token_id
    )
    marked = await last_used()
    await tokens.check(issued.token)
    assert await last_used() == marked
    clock.now += 1
    await tokens.check(issued.token)
    assert await last_used() != marked


async def test_listing_shows_a_members_tokens_in_a_server_without_secrets(tokens: Tokens) -> None:
    mine = await tokens.issue(GUILD, MEMBER, NewToken("claude"))
    await tokens.issue(GUILD, 7, NewToken("theirs"))
    await tokens.issue(9999, MEMBER, NewToken("elsewhere"))
    rows = await tokens.list(GUILD, MEMBER)
    assert [(r.token_id, r.label, r.user_id) for r in rows] == [(mine.token_id, "claude", MEMBER)]
    assert len(await tokens.list(GUILD, None)) == 2


async def test_defaults_are_write_and_thirty_days(tokens: Tokens, admin: Conn) -> None:
    issued = await tokens.issue(GUILD, MEMBER, NewToken("claude"))
    row = await admin.fetchrow(
        "SELECT max_risk, expires_at - created_at AS life FROM core.tokens WHERE id = $1", issued.token_id
    )
    assert row is not None and row["max_risk"] == Risk.WRITE and row["life"] == timedelta(days=30)

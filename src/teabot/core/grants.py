"""Work that outlasts its apply (role-changes.md): a grant is the apply's audit row, and a job that acts on it checks
it, as the core checks a call (D17 to D20), and records its outcome (D24).

A grant is good while: the row is an apply of the server's own action, of the plugin asking, ended "handed off"; the
plugin is still enabled there; the member is still in the server with the action's permissions; and a token that
made it is still valid, within its maximum risk and allow-list. A site sign-in that has since ended does not matter,
since the member confirmed the work.
"""

import json
from datetime import UTC, datetime
from typing import Any

from teabot.auth.tokens import Tokens
from teabot.core.audit import AuditLog
from teabot.core.registry import Call, Refused, Registry, TokenLimits, door_refusal
from teabot.sdk import Actor
from teabot.sdk.members import NotAuthorized

GRANT = """
SELECT action, guild_id, user_id, token_id, surface, input, outcome FROM core.audit_log WHERE id = $1
"""
OUTCOME = """
INSERT INTO core.audit_log (guild_id, user_id, token_id, surface, action, input, risk, outcome, error, follows)
SELECT guild_id, user_id, token_id, surface, action, $2::jsonb, risk, $3, $4, id FROM core.audit_log
WHERE id = $1 AND outcome = 'handed_off'
ON CONFLICT (follows) WHERE follows IS NOT NULL DO NOTHING
RETURNING id, guild_id
"""


class Grants:
    """Checks and closes grants for plugin jobs."""

    def __init__(self, registry: Registry, tokens: Tokens, audit: AuditLog) -> None:
        self.registry = registry
        self.tokens = tokens
        self.audit = audit

    async def authorized(self, guild_id: int, plugin_id: str, audit_id: int) -> Actor:
        """The grant's member, door and token, or `NotAuthorized` saying why it no longer holds."""
        try:
            return await self._check(guild_id, plugin_id, audit_id)
        except Refused as refusal:
            raise NotAuthorized(refusal.message) from None

    async def _check(self, guild_id: int, plugin_id: str, audit_id: int) -> Actor:
        row = await self.registry.pools.core_db().fetchrow(GRANT, audit_id)
        action = row["action"] if row is not None else ""
        if row is None or row["guild_id"] != guild_id or action.split(".")[0] != plugin_id:
            raise Refused("forbidden", "that is not a grant of this plugin in this server")
        if row["outcome"] != "handed_off":
            raise Refused("forbidden", "that grant is not a change handed off from its apply")
        if row["user_id"] == 0:
            raise Refused("forbidden", "the member who confirmed it has had their data deleted")
        actor = Actor(row["user_id"], row["surface"], row["token_id"])
        spec = self.registry.actions.get(action)
        if spec is None:
            raise Refused("unknown_action", f"there is no action {action}")
        limits = await self._token(actor, guild_id)
        if refusal := door_refusal(spec, actor.via, limits):
            raise refusal
        guild = self.registry.client.get_guild(guild_id)
        if guild is None:
            raise Refused("not_in_guild", "the bot is not in that server")
        call = Call(action, guild_id, actor, json.loads(row["input"]), limits)
        await self.registry.prepare(spec, call, guild, check_input=False)
        return actor

    async def _token(self, actor: Actor, guild_id: int) -> TokenLimits | None:
        if actor.token_id is None:
            return None
        token = await self.tokens.find(actor.token_id, guild_id)
        if token is None or token.expires_at <= datetime.now(UTC):
            raise Refused("forbidden", "the token that confirmed it has been revoked or has expired")
        return TokenLimits(token.max_risk, frozenset(token.allowed))

    async def record_outcome(self, guild_id: int, audit_id: int, text: str, *, failed: bool = False) -> None:
        """Close a handed-off apply with its outcome, once, as a row of its own, posted to the log channel."""
        details: dict[str, Any] = {"outcome": text}
        db = self.registry.pools.core_db()
        async with db.transaction() as tx:
            row = await tx.fetchrow(
                OUTCOME, audit_id, json.dumps(details), "error" if failed else "ok", text if failed else None
            )
            if row is not None and row["guild_id"] == guild_id:
                await self.audit.post(tx, guild_id, row["id"])

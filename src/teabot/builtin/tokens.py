"""`/tokens create | list | revoke` (D16, D17, D20): part of the core admin plugin, slash only.

Any member manages their own tokens. Listing or revoking other members' tokens needs Manage Server. The
token is shown once, in the ephemeral reply to `create`; the audit row holds the input, never the token.
"""

from collections.abc import Collection
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from teabot.auth.tokens import NewToken, TokenRow, Tokens
from teabot.builtin.config import AdminConfig
from teabot.core.registry import ActionSource, member_permissions
from teabot.sdk import ActionContext, ActionError, ActionSpec, Risk, Surface

type RiskName = Literal["read", "write", "destructive"]


class Create(BaseModel):
    label: str = Field(max_length=50, description="What the token is for, such as claude or battleships")
    max_risk: RiskName = Field(default="write", description="The riskiest actions it may use")
    days: int = Field(default=30, ge=1, le=365, description="How many days until it expires")
    actions: str | None = Field(default=None, description="Only these actions, comma separated")


class ListTokens(BaseModel):
    everyone: bool = Field(default=False, description="Everyone's tokens here, which needs Manage Server")


class Revoke(BaseModel):
    token_id: str = Field(max_length=32, description="The token's id, as /tokens list shows it")


class Created(BaseModel):
    token: str
    token_id: str
    max_risk: RiskName
    actions: list[str]
    expires_at: datetime


class TokenInfo(BaseModel):
    token_id: str
    user_id: int
    label: str
    max_risk: RiskName
    actions: list[str]
    expires_at: datetime
    last_used: datetime | None


class TokenList(BaseModel):
    tokens: list[TokenInfo]


class Revoked(BaseModel):
    token_id: str


def risk_name(risk: Risk) -> RiskName:
    names: dict[Risk, RiskName] = {Risk.READ: "read", Risk.WRITE: "write", Risk.DESTRUCTIVE: "destructive"}
    return names[risk]


def info(row: TokenRow) -> TokenInfo:
    return TokenInfo(
        token_id=row.token_id,
        user_id=row.user_id,
        label=row.label,
        max_risk=risk_name(row.max_risk),
        actions=list(row.allowed),
        expires_at=row.expires_at,
        last_used=row.last_used,
    )


def allow_list(text: str | None, known: Collection[str]) -> list[str]:
    names = sorted({name.strip() for name in (text or "").split(",") if name.strip()})
    unknown = [name for name in names if name not in known]
    if unknown:
        raise ActionError(f"There is no action {', '.join(unknown)}.")
    return names


async def manages_server(ctx: ActionContext) -> bool:
    return (await member_permissions(ctx.guild, ctx.actor.user_id)).manage_guild


class TokenCommands:
    """`known` holds every action name, set once the registry's actions are all known."""

    def __init__(self, tokens: Tokens) -> None:
        self.tokens = tokens
        self.known: Collection[str] = ()

    async def create(self, ctx: ActionContext, data: Create) -> Created:
        actions = allow_list(data.actions, self.known)
        risk = Risk[data.max_risk.upper()]
        new = NewToken(data.label, risk, timedelta(days=data.days), actions)
        issued = await self.tokens.issue(ctx.guild.id, ctx.actor.user_id, new)
        return Created(
            token=issued.token,
            token_id=issued.token_id,
            max_risk=data.max_risk,
            actions=actions,
            expires_at=issued.expires_at,
        )

    async def list_tokens(self, ctx: ActionContext, data: ListTokens) -> TokenList:
        if data.everyone and not await manages_server(ctx):
            raise ActionError("Listing everyone's tokens needs Manage Server.")
        rows = await self.tokens.list(ctx.guild.id, None if data.everyone else ctx.actor.user_id)
        return TokenList(tokens=[info(r) for r in rows])

    async def revoke(self, ctx: ActionContext, data: Revoke) -> Revoked:
        row = await self.tokens.find(data.token_id, ctx.guild.id)
        if row is None:
            raise ActionError(f"There is no live token {data.token_id} in this server.")
        if row.user_id != ctx.actor.user_id and not await manages_server(ctx):
            raise ActionError("Revoking someone else's token needs Manage Server.")
        await self.tokens.revoke(data.token_id, ctx.guild.id)
        return Revoked(token_id=data.token_id)

    def sources(self) -> dict[str, ActionSource]:
        table: list[tuple[str, str, type[BaseModel], type[BaseModel], Risk, Any, Any]] = [
            (
                "tokens.create",
                "Create a token that acts as you here",
                Create,
                Created,
                Risk.WRITE,
                self.create,
                render_created,
            ),
            (
                "tokens.list",
                "List your tokens here",
                ListTokens,
                TokenList,
                Risk.READ,
                self.list_tokens,
                render_list,
            ),
            ("tokens.revoke", "Revoke a token", Revoke, Revoked, Risk.WRITE, self.revoke, render_revoked),
        ]
        specs = {
            name: ActionSpec(name, summary, inp, out, risk, run, surfaces=Surface.SLASH, render=render)
            for name, summary, inp, out, risk, run, render in table
        }
        return {"tokens": ActionSource(AdminConfig, specs, builtin=True)}


def render_created(out: Created) -> str:
    scope = ", ".join(out.actions) if out.actions else "every action"
    return (
        f"Your token, shown only this once:\n```\n{out.token}\n```\n"
        f"It acts as you, up to `{out.max_risk}`, for {scope}, until {out.expires_at:%Y-%m-%d}. "
        f"Revoke it with `/tokens revoke {out.token_id}`."
    )


def render_list(out: TokenList) -> str:
    lines = [
        f"`{t.token_id}` {t.label} by <@{t.user_id}>, up to {t.max_risk}, until {t.expires_at:%Y-%m-%d}"
        for t in out.tokens
    ]
    return "\n".join(lines) or "No live tokens."


def render_revoked(out: Revoked) -> str:
    return f"Token `{out.token_id}` is revoked."

"""The interaction router (D29, D32): one handler for every teabot command and modal.

A command with a `LongText` field saves its other options as a draft row and opens a modal whose custom id
holds only the draft id, so any process can finish the submit (D40). Replies are ephemeral unless the action
asks for a public one; refusals say why, failures point at the audit log without leaking details.
"""

import json
import logging
import uuid
from collections.abc import Mapping
from typing import Any, Protocol

import discord
from pydantic import BaseModel

from teabot.adapters.schema import fold_lists, slash_fields
from teabot.core.plans import Planned, Queued
from teabot.core.registry import ActionFailed, Call, Refused
from teabot.db.pool import Database
from teabot.sdk import ActionSpec, Actor
from teabot.sdk.actions import Via
from teabot.sdk.components import PREFIX as BUTTON_PREFIX
from teabot.sdk.components import SELECT_PREFIX, parse_custom_id, parse_select_id
from teabot.sdk.fields import LONG_TEXT_MAX
from teabot.sdk.inputs import input_fields

log = logging.getLogger(__name__)

MODAL_PREFIX = "teabot:core:modal:"
EXPIRED = "That form has expired. Run the command again."
OUTSIDE = "teabot commands work inside a server."
FAILED = "That did not work. The error is in the audit log."
DRAFT_MINUTES = 15
FIELD_SHOWN = 1024

SAVE_DRAFT = """
INSERT INTO core.interaction_drafts (id, guild_id, user_id, action, input) VALUES ($1, $2, $3, $4, $5::jsonb)
"""
TAKE_DRAFT = """
DELETE FROM core.interaction_drafts
WHERE id = $1 AND guild_id = $2 AND user_id = $3 AND created_at > now() - make_interval(mins => $4)
RETURNING action, input
"""


class Invoker(Protocol):
    @property
    def actions(self) -> Mapping[str, ActionSpec[Any, Any]]: ...

    async def invoke(self, call: Call) -> BaseModel: ...


def default_embed(spec: ActionSpec[Any, Any], output: BaseModel) -> discord.Embed:
    """An embed with one field per output field, for actions without their own renderer (D29)."""
    embed = discord.Embed(title=spec.summary)
    for name, value in output.model_dump(mode="json").items():
        embed.add_field(name=name.replace("_", " ").capitalize(), value=str(value)[:FIELD_SHOWN])
    return embed


def _modal(spec: ActionSpec[Any, Any], draft_id: uuid.UUID, fields: tuple[str, ...]) -> discord.ui.Modal:
    modal = discord.ui.Modal(title=spec.summary[:45], custom_id=f"{MODAL_PREFIX}{draft_id}")
    described = {f.name: f for f in input_fields(spec.input)}
    for name in fields:
        modal.add_item(
            discord.ui.TextInput(
                label=described[name].description[:45],
                custom_id=name,
                style=discord.TextStyle.paragraph,
                max_length=LONG_TEXT_MAX,
                required=described[name].required,
            )
        )
    return modal


def _modal_values(data: Mapping[str, Any]) -> dict[str, str]:
    return {
        item["custom_id"]: item["value"] for row in data.get("components", []) for item in row["components"]
    }


CONFIRM_PREFIX = "teabot:core:confirm:"
PLAN_GONE = "That plan no longer exists. Run the command again for a new one."
BUTTON_GONE = "That button no longer works."
PLAN_SHOWN = 10
PLANNED = "SELECT action, input FROM core.audit_log WHERE confirm = $1 AND outcome = 'planned'"


def plan_embed(plan: Planned) -> discord.Embed:
    """A destructive command's diff (D21). Entry targets are member-written, so their markdown is escaped."""
    if plan.stale:
        note = "The target has changed since your last plan, so nothing was applied. This is the fresh plan."
    else:
        note = "Nothing has changed yet. Confirm within 15 minutes to apply it."
    embed = discord.Embed(title=f"Plan: {plan.action}", description=note, colour=discord.Colour.orange())
    embed.add_field(name="Changes", value=", ".join(f"{k}: {v}" for k, v in plan.counts.items()) or "none")
    lines = [
        f"{e.change} {discord.utils.escape_markdown(e.target)}"
        + (f": {discord.utils.escape_markdown(e.detail)}" if e.detail else "")
        for e in plan.entries[:PLAN_SHOWN]
    ]
    if plan.total > len(lines):
        lines.append(f"and {plan.total - len(lines)} more")
    embed.add_field(name="First entries", value="\n".join(lines) or "none", inline=False)
    return embed


def confirm_view(plan: Planned) -> discord.ui.View:
    """One Confirm button. Its custom id holds the confirm value alone, so any process can act on it (D40)."""
    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            label="Confirm", style=discord.ButtonStyle.danger, custom_id=f"{CONFIRM_PREFIX}{plan.confirm}"
        )
    )
    return view


class InteractionRouter:
    def __init__(self, registry: Invoker, db: Database) -> None:
        self.registry = registry
        self.db = db

    async def handle(self, interaction: Any) -> None:
        if interaction.type is discord.InteractionType.application_command:
            await self._command(interaction)
        elif interaction.type is discord.InteractionType.modal_submit and str(
            interaction.data.get("custom_id", "")
        ).startswith(MODAL_PREFIX):
            await self._modal_submit(interaction)
        elif interaction.type is discord.InteractionType.component and str(
            interaction.data.get("custom_id", "")
        ).startswith(CONFIRM_PREFIX):
            await self._confirm(interaction)
        elif interaction.type is discord.InteractionType.component and str(
            interaction.data.get("custom_id", "")
        ).startswith(BUTTON_PREFIX):
            await self._press(interaction)
        elif interaction.type is discord.InteractionType.component and str(
            interaction.data.get("custom_id", "")
        ).startswith(SELECT_PREFIX):
            await self._choose(interaction)

    async def _choose(self, interaction: Any) -> None:
        """A plugin's select menu: the bound call, with what the member chose filling its `into` parameter."""
        parsed = parse_select_id(str(interaction.data["custom_id"]))
        if parsed is None or interaction.guild_id is None:
            await interaction.response.send_message(BUTTON_GONE, ephemeral=True)
            return
        bound, into = parsed
        raw = dict(bound.input) | {into: list(interaction.data.get("values", []))}
        await self._run(interaction, bound.action, raw, via="component")

    async def _press(self, interaction: Any) -> None:
        """A plugin's button: the action and input its custom id holds, run as the member who pressed it,
        through the same call path as a slash command."""
        bound = parse_custom_id(str(interaction.data["custom_id"]))
        if bound is None or interaction.guild_id is None:
            await interaction.response.send_message(BUTTON_GONE, ephemeral=True)
            return
        await self._run(interaction, bound.action, dict(bound.input), via="component")

    async def _confirm(self, interaction: Any) -> None:
        """A Confirm press calls the action again with its plan's input and confirm value, through the same
        checks as MCP and the service API: the presser must be the member who planned it (D21)."""
        confirm = interaction.data["custom_id"].removeprefix(CONFIRM_PREFIX)
        row = await self.db.fetchrow(PLANNED, confirm)
        if row is None:
            await interaction.response.send_message(PLAN_GONE, ephemeral=True)
            return
        raw = json.loads(row["input"]) | {"confirm": confirm}
        await self._run(interaction, row["action"], raw, via="component")

    async def _command(self, interaction: Any) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(OUTSIDE, ephemeral=True)
            return
        sub = interaction.data["options"][0]
        name = f"{interaction.data['name']}.{sub['name']}"
        raw = {o["name"]: o["value"] for o in sub.get("options", [])}
        spec = self.registry.actions.get(name)
        if spec is not None:
            raw = fold_lists(spec.input, raw)
        modal_fields = slash_fields(spec.input).modal if spec is not None else ()
        if spec is not None and modal_fields:
            draft_id = uuid.uuid4()
            await self.db.execute(
                SAVE_DRAFT, draft_id, interaction.guild_id, interaction.user.id, name, json.dumps(raw)
            )
            await interaction.response.send_modal(_modal(spec, draft_id, modal_fields))
            return
        await self._run(interaction, name, raw)

    async def _modal_submit(self, interaction: Any) -> None:
        try:
            draft_id = uuid.UUID(interaction.data["custom_id"].removeprefix(MODAL_PREFIX))
        except ValueError:
            draft_id = None
        row = None
        if draft_id is not None:
            row = await self.db.fetchrow(
                TAKE_DRAFT, draft_id, interaction.guild_id, interaction.user.id, DRAFT_MINUTES
            )
        if row is None:
            await interaction.response.send_message(EXPIRED, ephemeral=True)
            return
        raw = json.loads(row["input"]) | _modal_values(interaction.data)
        await self._run(interaction, row["action"], raw)

    async def _run(self, interaction: Any, name: str, raw: dict[str, Any], via: Via = "slash") -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        call = Call(name, interaction.guild_id, Actor(interaction.user.id, via), raw)
        try:
            output = await self.registry.invoke(call)
        except Refused as refusal:
            await interaction.followup.send(refusal.message, ephemeral=True)
            return
        except ActionFailed as failure:
            await interaction.followup.send(failure.public_message or FAILED, ephemeral=True)
            return
        await self._reply(interaction, self.registry.actions[name], output)

    async def _reply(self, interaction: Any, spec: ActionSpec[Any, Any], output: BaseModel) -> None:
        if isinstance(output, Planned):
            view = confirm_view(output)
            await interaction.followup.send(embed=plan_embed(output), view=view, ephemeral=True)
            # The press arrives through on_interaction like any other, so discord.py need not keep the view.
            view.stop()
            return
        if isinstance(output, Queued):
            await interaction.followup.send(
                f"Applying. Follow it with `/admin job_status job_id:{output.job_id}`.", ephemeral=True
            )
            return
        rendered = spec.render(output) if spec.render is not None else default_embed(spec, output)
        private = spec.reply != "public"
        if not private:
            # The command was acknowledged privately, so a refusal stays private; a success is shown to the
            # channel as a follow-up, and the private placeholder goes.
            await interaction.delete_original_response()
        if isinstance(rendered, str):
            await interaction.followup.send(rendered, ephemeral=private)
        else:
            await interaction.followup.send(embed=rendered, ephemeral=private)


async def prune_drafts(db: Database, minutes: int = DRAFT_MINUTES) -> str:
    """Drop drafts nobody submitted. Run from the daily maintenance job."""
    return await db.execute(
        "DELETE FROM core.interaction_drafts WHERE created_at < now() - make_interval(mins => $1)", minutes
    )

"""The interaction router (D29, D32): one handler for every teapot command and modal.

A command with a `LongText` field saves its other options as a draft row and opens a modal whose custom id
holds only the draft id, so any process can finish the submit (D40). Every reply is ephemeral; refusals say
why, failures point at the audit log without leaking details.
"""

import json
import logging
import uuid
from collections.abc import Mapping
from typing import Any, Protocol

import discord
from pydantic import BaseModel

from teapot.adapters.schema import slash_fields
from teapot.core.registry import ActionFailed, Call, Refused
from teapot.db.pool import Database
from teapot.sdk import ActionSpec, Actor
from teapot.sdk.fields import LONG_TEXT_MAX
from teapot.sdk.inputs import input_fields

log = logging.getLogger(__name__)

MODAL_PREFIX = "teapot:core:modal:"
EXPIRED = "That form has expired. Run the command again."
OUTSIDE = "teapot commands work inside a server."
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

    async def _command(self, interaction: Any) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(OUTSIDE, ephemeral=True)
            return
        sub = interaction.data["options"][0]
        name = f"{interaction.data['name']}.{sub['name']}"
        raw = {o["name"]: o["value"] for o in sub.get("options", [])}
        spec = self.registry.actions.get(name)
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

    async def _run(self, interaction: Any, name: str, raw: dict[str, Any]) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        call = Call(name, interaction.guild_id, Actor(interaction.user.id, "slash"), raw)
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
        rendered = spec.render(output) if spec.render is not None else default_embed(spec, output)
        if isinstance(rendered, str):
            await interaction.followup.send(rendered, ephemeral=True)
        else:
            await interaction.followup.send(embed=rendered, ephemeral=True)


async def prune_drafts(db: Database, minutes: int = DRAFT_MINUTES) -> str:
    """Drop drafts nobody submitted. Run from the daily maintenance job."""
    return await db.execute(
        "DELETE FROM core.interaction_drafts WHERE created_at < now() - make_interval(mins => $1)", minutes
    )

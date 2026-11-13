"""teapot-announcements: post an announcement to a channel (D41). Imports only `teapot.sdk` (D45)."""

from typing import Any, Literal, cast

import discord
from pydantic import BaseModel, Field

from teapot.sdk import ActionContext, ActionError, ActionSpec, ChannelRef, LongText, Manifest, Registrar, Risk

COLOURS = {
    "blurple": discord.Colour.blurple(),
    "green": discord.Colour.green(),
    "red": discord.Colour.red(),
    "gold": discord.Colour.gold(),
}


class Post(BaseModel):
    channel: ChannelRef = Field(description="The channel to post in")
    title: str = Field(max_length=256, description="The announcement's title")
    body: LongText = Field(description="The announcement")
    colour: Literal["blurple", "green", "red", "gold"] = Field(
        default="blurple", description="The embed's colour"
    )


class Posted(BaseModel):
    message_id: int
    url: str


async def post(ctx: ActionContext, data: Post) -> Posted:
    channel = cast(Any, ctx.guild.get_channel(data.channel))
    if channel is None or not hasattr(channel, "send"):
        raise ActionError("That channel is not a text channel in this server.")
    embed = discord.Embed(title=data.title, description=data.body, colour=COLOURS[data.colour])
    try:
        message = await channel.send(embed=embed)
    except discord.Forbidden:
        raise ActionError("I am not allowed to post in that channel.") from None
    return Posted(message_id=message.id, url=message.jump_url)


POST = ActionSpec(
    "announcements.post",
    "Post an announcement",
    Post,
    Posted,
    Risk.WRITE,
    post,
    default_permissions=discord.Permissions(manage_messages=True),
    render=lambda out: f"Posted: {out.url}",
)


class Announcements:
    manifest = Manifest("announcements", "0.1.0")

    def setup(self, registrar: Registrar) -> None:
        registrar.action(POST)


plugin = Announcements()

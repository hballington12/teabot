"""teapot-announcements: post an announcement to a channel, now or later (D41). Imports only `teapot.sdk` (D45).

- `announcements.post` posts it now.
- `announcements.schedule` checks the channel now and queues a `post` job for later (D31). If the channel has
  gone by then, or the bot may no longer post there, the job fails with the reason, which `admin.job_status`
  shows.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

import discord
from pydantic import BaseModel, Field

from teapot.sdk import (
    ActionContext,
    ActionError,
    ActionSpec,
    ChannelRef,
    JobContext,
    LongText,
    Manifest,
    Registrar,
    Risk,
)

COLOURS = {
    "blurple": discord.Colour.blurple(),
    "green": discord.Colour.green(),
    "red": discord.Colour.red(),
    "gold": discord.Colour.gold(),
}
type Colour = Literal["blurple", "green", "red", "gold"]
MANAGE_MESSAGES = discord.Permissions(manage_messages=True)
NOT_TEXT = "That channel is not a text channel in this server."


class Post(BaseModel):
    channel: ChannelRef = Field(description="The channel to post in")
    title: str = Field(max_length=256, description="The announcement's title")
    body: LongText = Field(description="The announcement")
    colour: Colour = Field(default="blurple", description="The embed's colour")


class Schedule(Post):
    in_minutes: int = Field(ge=1, le=10080, description="Minutes from now, up to a week")


class Posted(BaseModel):
    message_id: int
    url: str


class Scheduled(BaseModel):
    job_id: int
    at: datetime


def text_channel(found: Any) -> Any | None:
    """The channel if it takes messages, else None."""
    return found if found is not None and hasattr(found, "send") else None


def embed_of(data: Post) -> discord.Embed:
    return discord.Embed(title=data.title, description=data.body, colour=COLOURS[data.colour])


async def send(channel: Any, embed: discord.Embed) -> Any:
    try:
        return await channel.send(embed=embed)
    except discord.Forbidden:
        raise ActionError("I am not allowed to post in that channel.") from None


async def post(ctx: ActionContext, data: Post) -> Posted:
    channel = text_channel(cast(Any, ctx.guild.get_channel(data.channel)))
    if channel is None:
        raise ActionError(NOT_TEXT)
    message = await send(channel, embed_of(data))
    return Posted(message_id=message.id, url=message.jump_url)


async def schedule(ctx: ActionContext, data: Schedule) -> Scheduled:
    if text_channel(cast(Any, ctx.guild.get_channel(data.channel))) is None:
        raise ActionError(NOT_TEXT)
    at = datetime.now(UTC) + timedelta(minutes=data.in_minutes)
    announcement = Post.model_validate(data.model_dump(exclude={"in_minutes"})).model_dump(mode="json")
    job_id = await ctx.queue.schedule("post", run_at=at, payload=announcement)
    return Scheduled(job_id=job_id, at=at)


async def post_later(ctx: JobContext) -> None:
    """The `post` job: the announcement `schedule` queued, posted when it is due."""
    data = Post.model_validate(ctx.payload)
    channel = text_channel(ctx.client.get_channel(data.channel))
    if channel is None:
        raise ActionError(f"Channel {data.channel} is no longer a text channel the bot can see.")
    await send(channel, embed_of(data))


def render_scheduled(out: Scheduled) -> str:
    return f"Scheduled for <t:{int(out.at.timestamp())}:f> (job {out.job_id})."


POST = ActionSpec(
    "announcements.post",
    "Post an announcement",
    Post,
    Posted,
    Risk.WRITE,
    post,
    default_permissions=MANAGE_MESSAGES,
    render=lambda out: f"Posted: {out.url}",
)
SCHEDULE = ActionSpec(
    "announcements.schedule",
    "Post an announcement later",
    Schedule,
    Scheduled,
    Risk.WRITE,
    schedule,
    default_permissions=MANAGE_MESSAGES,
    render=render_scheduled,
)


class Announcements:
    manifest = Manifest("announcements", "0.2.0")

    def setup(self, registrar: Registrar) -> None:
        registrar.action(POST)
        registrar.action(SCHEDULE)
        registrar.job("post", post_later)


plugin = Announcements()

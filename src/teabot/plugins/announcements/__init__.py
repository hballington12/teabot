"""teabot-announcements: post an announcement to a channel, now or later. Imports only `teabot.sdk`.

- `announcements.post` posts it now.
- `announcements.schedule` checks the channel now and queues the post for later. If the channel has gone
  by then, or the bot may no longer post there, the job fails with the reason, which `/admin job_status` shows.
"""

from datetime import datetime, timedelta
from typing import Annotated, Literal

import discord
from pydantic import BaseModel, Field

from teabot.sdk import ActionError, Context, EmptyConfig, LongText, Plugin, TextChannel

plugin = Plugin("announcements", description="Post announcements to a channel, now or at a time you choose.")
type Ctx = Context[EmptyConfig]

type Colour = Literal["blurple", "green", "red", "gold"]
COLOURS = {
    "blurple": discord.Colour.blurple(),
    "green": discord.Colour.green(),
    "red": discord.Colour.red(),
    "gold": discord.Colour.gold(),
}


class Posted(BaseModel):
    message_id: int
    url: str

    def render(self) -> str:
        return f"Posted: {self.url}"


class Scheduled(BaseModel):
    job_id: int
    at: datetime

    def render(self) -> str:
        return f"Scheduled for <t:{int(self.at.timestamp())}:f> (job {self.job_id})."


def embed_of(title: str, body: str, colour: Colour) -> discord.Embed:
    return discord.Embed(title=title, description=body, colour=COLOURS[colour])


@plugin.action(needs="manage_messages")
async def post(
    ctx: Ctx,
    channel: TextChannel,
    title: Annotated[str, Field(max_length=256)],
    body: LongText,
    colour: Colour = "blurple",
) -> Posted:
    """Post an announcement.

    Args:
        channel: The channel to post in
        title: The announcement's title
        body: The announcement
        colour: The embed's colour
    """
    message = await channel.send(embed=embed_of(title, body, colour))
    return Posted(message_id=message.id, url=message.jump_url)


@plugin.action(needs="manage_messages")
async def schedule(
    ctx: Ctx,
    channel: TextChannel,
    title: Annotated[str, Field(max_length=256)],
    body: LongText,
    in_minutes: Annotated[int, Field(ge=1, le=10080)],
    colour: Colour = "blurple",
) -> Scheduled:
    """Post an announcement later.

    Args:
        channel: The channel to post in
        title: The announcement's title
        body: The announcement
        in_minutes: Minutes from now, up to a week
        colour: The embed's colour
    """
    at = ctx.now + timedelta(minutes=in_minutes)
    async with ctx.db.transaction() as tx:
        job_id = await tx.schedule(
            post_later.bind(channel=channel.id, title=title, body=body, colour=colour), at=at
        )
    return Scheduled(job_id=job_id, at=at)


@plugin.job(name="post")
async def post_later(ctx: Ctx, channel: int, title: str, body: str, colour: Colour) -> None:
    found = ctx.guild.get_text_channel(channel)
    if found is None:
        raise ActionError(f"Channel {channel} is no longer a text channel the bot can see.")
    await found.send(embed=embed_of(title, body, colour))

"""The outbox's delivery (D31): the `core.post_message` job brings a post in `core.posts` to Discord.

A post row holds what the message should show now, at a version. Delivery sends it, or edits it, to that version,
so jobs for the same post can run in any order and a repeated one changes nothing. A send carries a nonce, so
Discord drops a retry within its window for repeats.
"""

import json
import logging
from typing import Any

import discord

from teabot.core.audit import ChannelSource
from teabot.core.queue import JobContext
from teabot.db.pool import Database
from teabot.sdk._outbox import decode

POST_MESSAGE = "post_message"
log = logging.getLogger(__name__)

POST = "SELECT * FROM core.posts WHERE id = $1"
SENT = "UPDATE core.posts SET message_id = $2, shown_version = $3, error = NULL WHERE id = $1"
SHOWN = "UPDATE core.posts SET shown_version = greatest(shown_version, $2), error = NULL WHERE id = $1"
FAILED = "UPDATE core.posts SET error = $2 WHERE id = $1"
# A send and an edit racing each other settle within a few rounds.
ROUNDS = 3


def _message(row: Any) -> dict[str, Any]:
    value = row["message"]
    return json.loads(value) if isinstance(value, str) else dict(value)


class Outbox:
    """The `core.post_message` handler."""

    def __init__(self, db: Database, client: ChannelSource) -> None:
        self.db = db
        self.client = client

    async def __call__(self, ctx: JobContext) -> None:
        await self.deliver(int(ctx.job.payload["post_id"]))

    async def deliver(self, post_id: int) -> None:
        """Bring the post to Discord as it is now. Discord refusing, or the channel being gone, is recorded on
        the post and not retried; Discord being down raises, so the job retries."""
        for _ in range(ROUNDS):
            row = await self.db.fetchrow(POST, post_id)
            if row is None or not await self._step(row):
                return

    async def _step(self, row: Any) -> bool:
        """One step towards what the post should show. Returns whether another step may be needed."""
        channel = self.client.get_channel(row["channel_id"])
        if channel is None:
            await self.db.execute(FAILED, row["id"], "That channel is gone, or I cannot see it.")
            return False
        try:
            if row["deleted"]:
                await self._delete(channel, row)
                return False
            if row["message_id"] is None:
                await self._send(channel, row)
                return True
            if row["shown_version"] >= row["version"]:
                return False
            await self._edit(channel, row)
            return True
        except discord.Forbidden:
            await self.db.execute(FAILED, row["id"], "I am not allowed to post in that channel.")
            log.warning("outbox post refused", extra={"post": row["id"], "guild": row["guild_id"]})
            return False

    async def _send(self, channel: Any, row: Any) -> None:
        kwargs = decode(_message(row))
        if kwargs["view"] is None:
            del kwargs["view"]
        sent = await channel.send(nonce=f"teabot{row['id']}", **kwargs)
        await self.db.execute(SENT, row["id"], int(sent.id), row["version"])

    async def _edit(self, channel: Any, row: Any) -> None:
        try:
            message = await channel.fetch_message(row["message_id"])
        except discord.NotFound:
            await self.db.execute(FAILED, row["id"], "The message was deleted in Discord.")
            await self.db.execute(SHOWN, row["id"], row["version"])
            return
        await message.edit(**decode(_message(row)))
        await self.db.execute(SHOWN, row["id"], row["version"])

    async def _delete(self, channel: Any, row: Any) -> None:
        if row["message_id"] is None:
            return
        try:
            message = await channel.fetch_message(row["message_id"])
            await message.delete()
        except discord.NotFound:
            return

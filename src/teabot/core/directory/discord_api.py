"""What the member directory asks Discord, over discord.py's HTTP client (D55)."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import discord
from discord.http import Route

from teabot.core.directory.reconcile import PAGE


@dataclass(frozen=True)
class Facts:
    member_count: int | None
    role_ids: frozenset[int]


class DiscordMembers:
    """The directory's `MemberApi` over the real client."""

    def __init__(self, client: discord.Client) -> None:
        self.client = client

    def shard_count(self) -> int:
        return self.client.shard_count or 1

    def bot_id(self) -> int | None:
        return self.client.user.id if self.client.user is not None else None

    def facts(self, guild_id: int) -> Facts | None:
        guild = self.client.get_guild(guild_id)
        if guild is None or guild.unavailable:
            return None
        return Facts(guild.member_count, frozenset(r.id for r in guild.roles))

    async def list_members(self, guild_id: int, after: int) -> list[Mapping[str, Any]]:
        """One page of Discord's documented member list, in user ID order."""
        return list(await self.client.http.get_members(guild_id, PAGE, after or None))

    async def search_members(self, guild_id: int, body: Mapping[str, Any]) -> Any:
        """Discord's member search, which its published docs do not list (S9)."""
        route = Route("POST", "/guilds/{guild_id}/members-search", guild_id=guild_id)
        return await self.client.http.request(route, json=dict(body))

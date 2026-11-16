"""teabot-roles: a post with a button for each role, which members press to take the role and press again to give
it back. Imports only `teabot.sdk`.

- `roles.post` posts a set of roles, each as a button.
- `roles.add` and `roles.remove` change a post's roles, and update it in place.
- `roles.list` shows the server's posts.
- `roles.delete` deletes a post, after a plan.
- `roles.toggle` is what a button press runs: it gives the role, or takes it back.

A button gives a member a role they could not give themselves, so only safe roles are offered: none that Discord
manages, none that grants a moderator's permission, and none at or above the bot's highest role or the highest role
of the member who offers it. A press checks again, so a role changed since it was offered stops working.
"""

from typing import Annotated

from pydantic import BaseModel, Field

from teabot.sdk import (
    DESTRUCTIVE,
    READ,
    ActionError,
    Button,
    Choice,
    Context,
    Diff,
    DiffEntry,
    EmptyConfig,
    Member,
    Permission,
    Plugin,
    Role,
    Surface,
    TextChannel,
    UntrustedText,
)

plugin = Plugin(
    "roles", description="Posts with a button for each role, which members press to take it or give it back."
)
type Ctx = Context[EmptyConfig]

BUTTONS_MAX = 25
DANGEROUS: frozenset[Permission] = frozenset(
    {
        "administrator",
        "ban_members",
        "kick_members",
        "manage_channels",
        "manage_events",
        "manage_expressions",
        "manage_guild",
        "manage_messages",
        "manage_nicknames",
        "manage_roles",
        "manage_threads",
        "manage_webhooks",
        "mention_everyone",
        "moderate_members",
        "move_members",
        "mute_members",
        "deafen_members",
        "view_audit_log",
    }
)

NEW_POST = "INSERT INTO posts (guild_id, channel_id, title, note) VALUES ($1, $2, $3, $4) RETURNING id"
SET_MESSAGE = "UPDATE posts SET message_id = $3 WHERE guild_id = $1 AND id = $2"
OFFER = """
INSERT INTO offers (guild_id, post_id, role_id, place)
SELECT $1, $2, $3, coalesce(max(place), 0) + 1 FROM offers WHERE guild_id = $1 AND post_id = $2
ON CONFLICT DO NOTHING
"""
WITHDRAW = "DELETE FROM offers WHERE guild_id = $1 AND post_id = $2 AND role_id = $3"
ONE_POST = "SELECT id, channel_id, message_id, title, note FROM posts WHERE guild_id = $1 AND id = $2"
OFFERED = "SELECT role_id FROM offers WHERE guild_id = $1 AND post_id = $2 ORDER BY place"
IS_OFFERED = "SELECT EXISTS (SELECT 1 FROM offers WHERE guild_id = $1 AND post_id = $2 AND role_id = $3)"
ALL_POSTS = """
SELECT p.id, p.title, p.channel_id, count(o.role_id) AS roles
FROM posts p LEFT JOIN offers o ON o.guild_id = p.guild_id AND o.post_id = p.id
WHERE p.guild_id = $1 GROUP BY p.id ORDER BY p.id
"""
DELETE_POST = "DELETE FROM posts WHERE guild_id = $1 AND id = $2"


class Post(BaseModel):
    id: int
    channel_id: int
    message_id: int | None
    title: str
    note: str


class Listed(BaseModel):
    id: int
    title: UntrustedText
    channel_id: int
    roles: int

    def render(self) -> str:
        return f"{self.id}: {self.title} in <#{self.channel_id}>, {self.roles} roles"


class Posted(BaseModel):
    post: int
    url: str

    def render(self) -> str:
        return f"Posted role picker {self.post}: {self.url}"


def _words(permission: str) -> str:
    return permission.replace("_", " ").title()


def refusal(guild_id: int, owner_id: int, bot: Member, role: Role, offerer: Member | None) -> str | None:
    """Why `role` may not be given out by a button, or None when it may."""
    if role.id == guild_id:
        return "Everyone has @everyone already."
    if role.managed:
        return f"{role.name} is managed by Discord or an integration, so nobody can give it out."
    risky = sorted(role.permissions & DANGEROUS)
    if risky:
        return f"{role.name} grants {', '.join(_words(p) for p in risky)}, so a button cannot give it out."
    if bot.top_role is None or role.position >= bot.top_role.position:
        return f"{role.name} is at or above my highest role. Move my role above it in Server Settings, then Roles."
    if offerer is not None and offerer.id != owner_id:
        top = offerer.top_role
        if top is None or role.position >= top.position:
            return f"{role.name} is at or above your highest role, so you cannot give it out."
    return None


async def check_offerable(ctx: Ctx, roles: list[Role]) -> None:
    offerer = await ctx.guild.get_member(ctx.actor.user_id)
    for role in roles:
        reason = refusal(ctx.guild.id, ctx.guild.owner_id, ctx.guild.me, role, offerer)
        if reason is not None:
            raise ActionError(reason)


async def found_post(ctx: Ctx, post: int) -> Post:
    row = await ctx.db.fetchrow(Post, ONE_POST, ctx.guild.id, post)
    if row is None:
        raise ActionError("No role picker has that number. /roles list shows them.")
    return row


def content(title: str, note: str) -> str:
    lines = [f"**{title}**", note, "Press a button to take that role, and press it again to give it back."]
    return "\n".join(line for line in lines if line)


def buttons(post: int, roles: list[Role]) -> list[Button]:
    return [Button(toggle.bind(post=post, role=r), label=r.name, style="primary") for r in roles]


async def offered_roles(ctx: Ctx, post: int) -> list[Role]:
    ids = await ctx.db.fetch(int, OFFERED, ctx.guild.id, post)
    return [role for role in (ctx.guild.get_role(i) for i in ids) if role is not None]


async def refresh(ctx: Ctx, found: Post) -> None:
    """Show the post's roles as they are now."""
    channel = ctx.guild.get_text_channel(found.channel_id)
    message = await channel.get_message(found.message_id) if channel and found.message_id else None
    if message is None:
        raise ActionError(
            "That role picker's post has been deleted. Delete it with /roles delete, and post again."
        )
    await message.edit(
        content(found.title, found.note), buttons=buttons(found.id, await offered_roles(ctx, found.id))
    )


@plugin.action(needs="manage_roles")
async def post(
    ctx: Ctx,
    channel: TextChannel,
    title: Annotated[str, Field(max_length=100)],
    roles: Annotated[list[Role], Field(min_length=1, max_length=10)],
    note: Annotated[str, Field(max_length=500)] = "",
) -> Posted:
    """Post a role picker: a button for each role.

    Args:
        channel: Where to post it
        title: The post's title, such as "Pick your pings"
        roles: The roles members can take
        note: A line under the title
    """
    await check_offerable(ctx, roles)
    async with ctx.db.transaction() as tx:
        picker = await tx.fetchval(int, NEW_POST, ctx.guild.id, channel.id, title, note)
        for role in roles:
            await tx.execute(OFFER, ctx.guild.id, picker, role.id)
    sent = await channel.send(content(title, note), buttons=buttons(picker, roles))
    await ctx.db.execute(SET_MESSAGE, ctx.guild.id, picker, sent.id)
    return Posted(post=picker, url=sent.jump_url)


@plugin.action(needs="manage_roles")
async def add(ctx: Ctx, post: int, role: Role) -> str:
    """Add a role to a role picker.

    Args:
        post: The role picker's number
        role: The role to add
    """
    found = await found_post(ctx, post)
    await check_offerable(ctx, [role])
    if len(await offered_roles(ctx, post)) >= BUTTONS_MAX:
        raise ActionError(f"A role picker holds at most {BUTTONS_MAX} roles.")
    await ctx.db.execute(OFFER, ctx.guild.id, post, role.id)
    await refresh(ctx, found)
    return f"{role.name} is now on role picker {post}."


@plugin.action(needs="manage_roles")
async def remove(ctx: Ctx, post: int, role: Role) -> str:
    """Take a role off a role picker. Members keep it if they have it.

    Args:
        post: The role picker's number
        role: The role to take off
    """
    found = await found_post(ctx, post)
    await ctx.db.execute(WITHDRAW, ctx.guild.id, post, role.id)
    await refresh(ctx, found)
    return f"{role.name} is no longer on role picker {post}."


@plugin.action(risk=READ, needs="manage_roles")
async def list_(ctx: Ctx) -> list[Listed]:
    """The server's role pickers."""
    return await ctx.db.fetch(Listed, ALL_POSTS, ctx.guild.id)


@plugin.action(surfaces=Surface.COMPONENT)
async def toggle(ctx: Ctx, post: int, role: Role) -> str:
    """Take a role from a role picker, or give it back. Only a role picker's buttons run this.

    Args:
        post: The role picker's number
        role: The role
    """
    if not await ctx.db.fetchval(bool, IS_OFFERED, ctx.guild.id, post, role.id):
        raise ActionError(f"{role.name} is no longer offered here.")
    reason = refusal(ctx.guild.id, ctx.guild.owner_id, ctx.guild.me, role, None)
    if reason is not None:
        raise ActionError(reason)
    member = await ctx.guild.get_member(ctx.actor.user_id)
    if member is None:
        raise ActionError("You are not in this server.")
    if role.id in member.role_ids:
        await member.remove_role(role)
        return f"{role.name} removed."
    await member.add_role(role)
    return f"You now have {role.name}."


@plugin.action(risk=DESTRUCTIVE, needs="manage_roles")
async def delete(ctx: Ctx, post: int) -> str:
    """Delete a role picker and its post. Members keep the roles they took.

    Args:
        post: The role picker's number
    """
    found = await found_post(ctx, post)
    channel = ctx.guild.get_text_channel(found.channel_id)
    message = await channel.get_message(found.message_id) if channel and found.message_id else None
    if message is not None:
        await message.delete()
    await ctx.db.execute(DELETE_POST, ctx.guild.id, post)
    return f"Deleted role picker {post}."


@delete.plan
async def plan_delete(ctx: Ctx, post: int) -> Diff:
    found = await found_post(ctx, post)
    roles = await offered_roles(ctx, post)
    detail = f"{len(roles)} roles: {', '.join(r.name for r in roles)}" if roles else "no roles"
    return Diff(entries=[DiffEntry(change="delete", target=found.title, detail=detail, key=found.id)])


@add.autocomplete("post")
@remove.autocomplete("post")
@delete.autocomplete("post")
async def pickers(ctx: Ctx, typed: str) -> list[Choice[int]]:
    rows = await ctx.db.fetch(Listed, ALL_POSTS, ctx.guild.id)
    return [
        Choice(f"{r.id}: {r.title}"[:100], r.id) for r in rows if typed.lower() in f"{r.id} {r.title}".lower()
    ]

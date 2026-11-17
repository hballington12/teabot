"""Who may give or take which role (role-changes.md): the bot's own limits, and with `by=`, the member's.

Discord compares only the role's position, never the target member's, so no target is ever refused for their rank.
The permission rule for giving is stricter than Discord's on purpose: nobody hands out a permission through the bot
without having it. It reads server permissions only, not channel overwrites.
"""

from typing import Any

import discord

from teabot.sdk.actions import ActionError

REASON_MAX = 512
# Discord's "unknown member" and "unknown user" (S10).
MEMBER_GONE_CODES = frozenset({10007, 10013})


class MemberGone(ActionError):
    """The member is no longer in the server, or there is no such Discord user."""


def _words(permission: str) -> str:
    return permission.replace("_", " ").title()


def _top(member: Any, guild: Any) -> int:
    roles = [r for r in getattr(member, "roles", ()) if int(r.id) != int(guild.id)]
    return max((int(r.position) for r in roles), default=0)


def _grants(member: Any) -> int:
    """Everything a member holds across the server, as discord.py works it out from their roles and @everyone's;
    Administrator holds every permission."""
    held = member.guild_permissions
    return discord.Permissions.all().value if held.administrator else int(held.value)


def _value(role: Any) -> int:
    grants = getattr(role, "grants", None)
    permissions = grants if grants is not None else role.permissions
    return int(permissions.value)


def bot_problem(guild: Any, role: Any) -> str | None:
    """Why the bot cannot give or take `role` itself, or None."""
    if int(role.id) == int(guild.id):
        return "Everyone has @everyone; it cannot be given or taken."
    if role.managed:
        return f"{role.name} is managed by Discord or an integration, so nobody can give or take it."
    if int(role.position) >= _top(guild.me, guild):
        return (
            f"{role.name} is at or above my highest role, so I cannot give or take it. "
            "Move my role above it in Server Settings, then Roles."
        )
    return None


def member_problem(guild: Any, role: Any, by: Any, *, give: bool) -> str | None:
    """Why `by`, a raw member, may not have the bot give or take `role` for them, or None. The owner may always."""
    if int(by.id) == int(guild.owner_id):
        return None
    held = _grants(by)
    every = discord.Permissions.all().value
    if held != every and not held & discord.Permissions(manage_roles=True).value:
        return f"Giving or taking {role.name} needs Manage Roles."
    if int(role.position) >= _top(by, guild):
        return f"{role.name} is at or above your highest role, so you cannot give or take it."
    if give:
        missing = [name for name, on in discord.Permissions(_value(role) & ~held) if on]
        if missing:
            return (
                f"{role.name} grants {', '.join(_words(p) for p in sorted(missing))}, which you do not have."
            )
    return None


def problem(guild: Any, role: Any, by: Any | None, *, give: bool) -> str | None:
    """Every check for one role change, the bot's first."""
    return bot_problem(guild, role) or (
        member_problem(guild, role, by, give=give) if by is not None else None
    )


def reason_text(base: str, action: str, by: Any | None, extra: str | None) -> str:
    """Discord's audit reason: teabot's own part, naming `by` when given, then any reason of the plugin's."""
    head = f"via teabot: {action}, for member {int(by.id)}" if by is not None and action else base
    return (f"{head}: {extra}" if extra else head)[:REASON_MAX]

"""Role changes for members (role-changes.md): give a role, or take it away, from up to ten named members, or from
every member a filter over the member directory matches, up to 10,000.

- `roles.give` and `roles.take` change named members inside the core's apply, in seconds.
- `roles.give_matching` and `roles.take_matching` change matching members: the apply stores the change and hands it
  to the `run_change` job, which works in short bursts, paced below Discord's limit of 10 role changes per 10
  seconds (S10), checking its grant and each member again as it goes.
- `roles.list_changes`, `roles.stop` and `roles.revert` follow, stop and undo matching changes.

Every change is made `by=` the member who confirmed it, so the bot never gives a role they could not give
themselves, and Discord's audit log names them. Through an AI assistant's token, a role with a dangerous permission
is never given or taken, since an assistant confirms its own plans.
"""

import json
import re
from datetime import datetime, timedelta
from typing import Annotated, Any

from pydantic import BaseModel, Field

from teabot.sdk import (
    DANGEROUS,
    DESTRUCTIVE,
    READ,
    ActionError,
    Context,
    Diff,
    DiffEntry,
    DirectoryUnavailable,
    EmptyConfig,
    HandedOff,
    Member,
    MemberFilter,
    MemberGone,
    NotAuthorized,
    PeopleFilter,
    Role,
    Surface,
    UntrustedText,
)

from . import plugin

type Ctx = Context[EmptyConfig]

NAMED_MAX = 10
MATCHING_MAX = 10_000
# Discord allows 10 role changes per 10 seconds in a server (S10); a change makes 8, leaving 2 for pickers.
BURST = 8
WINDOW = timedelta(seconds=10)
PER_SECOND = BURST / WINDOW.total_seconds()
CLAIM = timedelta(minutes=5)
RETRY = timedelta(minutes=1)
STALL = timedelta(days=1)
KEEP = timedelta(days=30)
# A snapshot this much larger than the plan is refused, so a raid cannot grow a change unseen.
GROWTH = 1.1
SHOWN = 10
TOKEN_DOORS = frozenset({"mcp", "service"})
COUNT_NOTE = re.compile(r"^([\d,]+) members? change")

OPEN = """
SELECT id, role_id, give, filter, grant_id, state, next_at, progress_at FROM role_changes
WHERE guild_id = $1 AND state IN ('queued', 'running', 'stopping') ORDER BY id LIMIT 1 FOR UPDATE
"""
CLAIM_IT = """
UPDATE role_changes SET next_at = $3, state = CASE WHEN state = 'queued' THEN 'running' ELSE state END,
    started_at = coalesce(started_at, $4), progress_at = coalesce(progress_at, $4)
WHERE guild_id = $1 AND id = $2
"""
PENDING = """
SELECT user_id FROM role_change_members WHERE guild_id = $1 AND change_id = $2 AND outcome = 'pending'
ORDER BY user_id LIMIT $3
"""
MARK = "UPDATE role_change_members SET outcome = $4 WHERE guild_id = $1 AND change_id = $2 AND user_id = $3"
PROGRESS = "UPDATE role_changes SET progress_at = $3, next_at = $4 WHERE guild_id = $1 AND id = $2"
WAIT = "UPDATE role_changes SET next_at = $3 WHERE guild_id = $1 AND id = $2"
FINISH = """
UPDATE role_changes SET state = $3, why = $4, finished_at = $5 WHERE guild_id = $1 AND id = $2
"""
COUNTS = """
SELECT outcome, count(*) AS n FROM role_change_members WHERE guild_id = $1 AND change_id = $2 GROUP BY outcome
"""
FORGET = "DELETE FROM role_changes WHERE guild_id = $1 AND finished_at < $2"
NEW_CHANGE = """
INSERT INTO role_changes (guild_id, role_id, give, filter, grant_id, reverts) VALUES ($1, $2, $3, $4, $5, $6)
RETURNING id
"""
NEW_MEMBERS = """
INSERT INTO role_change_members (guild_id, change_id, user_id) SELECT $1, $2, unnest($3::bigint[])
"""
WAITING = (
    "SELECT count(*) FROM role_changes WHERE guild_id = $1 AND state IN ('queued', 'running', 'stopping')"
)
LISTED = """
SELECT c.id, c.role_id, c.give, c.state, c.why, c.created_at, c.finished_at,
       count(*) FILTER (WHERE m.outcome = 'changed') AS changed,
       count(*) FILTER (WHERE m.outcome = 'gone') AS gone,
       count(*) FILTER (WHERE m.outcome = 'skipped') AS skipped,
       count(*) FILTER (WHERE m.outcome = 'pending') AS pending
FROM role_changes c LEFT JOIN role_change_members m ON m.guild_id = c.guild_id AND m.change_id = c.id
WHERE c.guild_id = $1 GROUP BY c.id ORDER BY c.id DESC LIMIT 25
"""
ONE = "SELECT id, role_id, give, state FROM role_changes WHERE guild_id = $1 AND id = $2"
STOP = """
UPDATE role_changes SET state = 'stopping', why = $3
WHERE guild_id = $1 AND id = $2 AND state IN ('queued', 'running')
"""
CHANGED = """
SELECT user_id FROM role_change_members WHERE guild_id = $1 AND change_id = $2 AND outcome = 'changed'
ORDER BY user_id
"""


class Listed(BaseModel):
    id: int
    role_id: int
    give: bool
    state: str
    why: UntrustedText | None
    changed: int
    gone: int
    skipped: int
    pending: int
    created_at: datetime
    finished_at: datetime | None


def _verb(give: bool) -> str:
    return "give" if give else "take"


def _plural(n: int, one: str) -> str:
    return f"{n:,} {one}" if n == 1 else f"{n:,} {one}s"


def _refuse_dangerous(ctx: Ctx, role: Role) -> None:
    """Through an assistant's token, never a role with a dangerous permission, giving or taking."""
    if ctx.actor.via in TOKEN_DOORS and role.permissions & DANGEROUS:
        raise ActionError(
            f"{role.name} grants a moderator's permission, so an AI assistant cannot give or take it. "
            "Change it in Discord or on the site."
        )


async def _confirmer(ctx: Ctx) -> Member:
    member = await ctx.guild.get_member(ctx.actor.user_id)
    if member is None:
        raise ActionError("You are not in this server.")
    return member


async def _assignable(ctx: Ctx, role: Role, give: bool) -> Member:
    """The member asking, once every rule for the change passes; else `ActionError` says why."""
    _refuse_dangerous(ctx, role)
    by = await _confirmer(ctx)
    if why := ctx.guild.can_assign(role, by=by, give=give):
        raise ActionError(why)
    return by


RULED = "SELECT id FROM rules WHERE guild_id = $1 AND $2 = ANY(roles) LIMIT 1"


async def _ruled_note(ctx: Ctx, role: Role) -> list[str]:
    rule = await ctx.db.fetchval(RULED, ctx.guild.id, role.id)
    return [] if rule is None else [f"Rule {rule} owns {role.name}, and undoes this change on its next run."]


def _dangerous_note(role: Role) -> list[str]:
    risky = sorted(role.permissions & DANGEROUS)
    if not risky:
        return []
    return [f"{role.name} grants {', '.join(p.replace('_', ' ').title() for p in risky)}."]


# Named changes: up to ten members, applied inside the core's apply.


async def _plan_named(ctx: Ctx, role: Role, members: list[Member], give: bool) -> Diff:
    await _assignable(ctx, role, give)
    entries: list[DiffEntry] = []
    for member in members:
        has = role.id in member.role_ids
        change = "skip" if has == give else _verb(give)
        why = (" already has it" if has else " lacks it") if change == "skip" else None
        entries.append(DiffEntry(change=change, target=member.display_name, detail=why, key=member.id))
    return Diff(entries=entries, notes=[*await _ruled_note(ctx, role), *_dangerous_note(role)])


async def _apply_named(ctx: Ctx, role: Role, give: bool) -> str:
    by = await _assignable(ctx, role, give)
    done = gone = 0
    for entry in ctx.diff.entries:
        if entry.change != _verb(give) or entry.key is None:
            continue
        try:
            if give:
                await ctx.guild.add_role(int(entry.key), role, by=by)
            else:
                await ctx.guild.remove_role(int(entry.key), role, by=by)
            done += 1
        except MemberGone:
            gone += 1
        await ctx.report({"done": done + gone, "total": len(ctx.diff.entries)})
    left = f", and {_plural(gone, 'member')} had left" if gone else ""
    return f"{'Gave' if give else 'Took'} {role.name} {'to' if give else 'from'} {_plural(done, 'member')}{left}."


Members = Annotated[list[Member], Field(min_length=1, max_length=NAMED_MAX)]


@plugin.action(risk=DESTRUCTIVE, needs="manage_roles")
async def give(ctx: Ctx, role: Role, members: Members) -> str:
    """Give a role to up to ten named members. It changes members, not a role picker; roles.add changes a picker.

    Args:
        role: The role to give
        members: The members to give it to
    """
    return await _apply_named(ctx, role, give=True)


@give.plan
async def plan_give(ctx: Ctx, role: Role, members: Members) -> Diff:
    return await _plan_named(ctx, role, members, give=True)


@plugin.action(risk=DESTRUCTIVE, needs="manage_roles")
async def take(ctx: Ctx, role: Role, members: Members) -> str:
    """Take a role from up to ten named members. It changes members, not a role picker; roles.remove changes a
    picker.

    Args:
        role: The role to take
        members: The members to take it from
    """
    return await _apply_named(ctx, role, give=False)


@take.plan
async def plan_take(ctx: Ctx, role: Role, members: Members) -> Diff:
    return await _plan_named(ctx, role, members, give=False)


# Matching changes: every member a filter matches, run as a job.


def _with_role(filter: MemberFilter, role: Role, give: bool) -> PeopleFilter:
    """The filter, narrowed to members the change would change: give needs them to lack the role, take to have it."""
    data = filter.model_dump()
    if give:
        data["roles_none"] = [*data["roles_none"], role.id]
    else:
        data["roles_all"] = [*data["roles_all"], role.id]
    return PeopleFilter.model_construct(**data)


async def _all_ids(ctx: Ctx, filter: MemberFilter, at_most: int) -> list[int]:
    """The IDs of the present members a filter matches, in pages, stopping one past `at_most`."""
    ids: list[int] = []
    after = 0
    while len(ids) <= at_most:
        page = await ctx.members.find(filter, after=after, limit=1000)
        ids.extend(m.user_id for m in page)
        if len(page) < 1000:
            break
        after = page[-1].user_id
    return ids


def _sentence(role: Role, filter: MemberFilter, give: bool) -> str:
    """The change in words, so a role and filter swapped by mistake show at once."""
    named = {r: f"<@&{r}>" for r in (*filter.roles_any, *filter.roles_all, *filter.roles_none)}
    parts: list[str] = []
    if filter.roles_any:
        parts.append("who have " + " or ".join(named[r] for r in filter.roles_any))
    if filter.roles_all:
        parts.append("who have " + " and ".join(named[r] for r in filter.roles_all))
    if filter.roles_none:
        parts.append("who have none of " + ", ".join(named[r] for r in filter.roles_none))
    if filter.joined_after or filter.joined_before:
        parts.append(
            f"who joined between {filter.joined_after or 'the start'} and {filter.joined_before or 'now'}"
        )
    who = ", ".join(parts) or "every present member"
    people = "members" if filter.bots is not False else "people"
    if give:
        return f"Give {role.name} to {people} {who}, and who lack {role.name}."
    return f"Take {role.name} from {people} {who}, and who have {role.name}."


async def _plan_matching(ctx: Ctx, role: Role, filter: PeopleFilter, give: bool) -> Diff:
    by = await _assignable(ctx, role, give)
    narrowed = _with_role(filter, role, give)
    matching = await ctx.members.count(filter)
    count = await ctx.members.count(narrowed)
    if count > MATCHING_MAX:
        raise ActionError(
            f"That change is to {count:,} members, and one change holds at most {MATCHING_MAX:,}. "
            "Split it, such as by join date."
        )
    shown = await ctx.members.find(narrowed, limit=SHOWN)
    top = by.top_role.position if by.top_role is not None else 0
    above = sum(
        1 for m in shown if any((r := ctx.guild.get_role(i)) and r.position >= top for i in m.role_ids)
    )
    minutes = max(1, round(count / PER_SECOND / 60))
    waiting = await ctx.db.fetchval(int, WAITING, ctx.guild.id)
    already = "already have" if give else "do not have"
    notes = [
        _sentence(role, filter, give),
        f"{_plural(count, 'member')} change. {matching:,} match, {matching - count:,} {already} {role.name}.",
        *await _ruled_note(ctx, role),
        *_dangerous_note(role),
        f"It should take about {minutes} minutes."
        if minutes < 120
        else f"It should take about {minutes // 60} hours.",
        "Among the first shown: " + ", ".join(m.display_name for m in shown) if shown else "Nobody matches.",
    ]
    if above:
        notes.append(f"{above} of the first {len(shown)} rank at or above your highest role.")
    if waiting:
        notes.append(f"It waits behind {_plural(waiting, 'change')} still running here.")
    if ctx.actor.via in TOKEN_DOORS:
        notes.append("The change stops if the token that confirms it expires or is revoked.")
    key = json.dumps(
        {
            "role": role.id,
            "permissions": sorted(role.permissions),
            "position": role.position,
            "give": give,
            "filter": filter.model_dump(mode="json"),
        },
        sort_keys=True,
    )
    entry = DiffEntry(change=_verb(give), target=role.name, key=key)
    return Diff(entries=[entry], notes=notes)


def _planned_count(diff: Diff) -> int | None:
    for note in diff.notes:
        if found := COUNT_NOTE.match(note):
            return int(found.group(1).replace(",", ""))
    return None


async def _apply_matching(ctx: Ctx, role: Role, filter: PeopleFilter, give: bool) -> HandedOff:
    await _assignable(ctx, role, give)
    if ctx.audit_id is None:
        raise ActionError("A matching change runs from a confirmed plan.")
    ids = await _all_ids(ctx, _with_role(filter, role, give), MATCHING_MAX)
    planned = _planned_count(ctx.diff)
    if len(ids) > MATCHING_MAX or (planned is not None and len(ids) > max(planned * GROWTH, planned + 5)):
        raise ActionError(
            f"The change has grown to {len(ids):,} members since its plan. Plan it again to see who it now holds."
        )
    async with ctx.db.transaction() as tx:
        change = await tx.fetchval(
            int, NEW_CHANGE, ctx.guild.id, role.id, give, filter.model_dump_json(), ctx.audit_id, None
        )
        await tx.execute(NEW_MEMBERS, ctx.guild.id, change, ids)
        await tx.schedule(run_change.bind(), at=ctx.now)
    return HandedOff(
        id=str(change),
        text=f"Change {change} is under way: {_verb(give)} {role.name}, {_plural(len(ids), 'member')}. "
        "roles.list_changes follows it.",
    )


MATCHING = Surface.MCP | Surface.SERVICE | Surface.WEB


@plugin.action(risk=DESTRUCTIVE, needs=("manage_roles", "manage_guild"), surfaces=MATCHING)
async def give_matching(ctx: Ctx, role: Role, filter: PeopleFilter) -> HandedOff:
    """Give a role to every present member a filter matches, up to 10,000, a few a second.

    Args:
        role: The role to give
    """
    return await _apply_matching(ctx, role, filter, give=True)


@give_matching.plan
async def plan_give_matching(ctx: Ctx, role: Role, filter: PeopleFilter) -> Diff:
    return await _plan_matching(ctx, role, filter, give=True)


@plugin.action(risk=DESTRUCTIVE, needs=("manage_roles", "manage_guild"), surfaces=MATCHING)
async def take_matching(ctx: Ctx, role: Role, filter: PeopleFilter) -> HandedOff:
    """Take a role from every present member a filter matches, up to 10,000, a few a second.

    Args:
        role: The role to take
    """
    return await _apply_matching(ctx, role, filter, give=False)


@take_matching.plan
async def plan_take_matching(ctx: Ctx, role: Role, filter: PeopleFilter) -> Diff:
    return await _plan_matching(ctx, role, filter, give=False)


# The job.


async def _counts(ctx: Ctx, change: int) -> dict[str, int]:
    rows = await ctx.db.fetch(COUNTS, ctx.guild.id, change)
    return {r["outcome"]: int(r["n"]) for r in rows}


async def _finish(ctx: Ctx, row: Any, state: str, why: str | None) -> None:
    """End a change, record its outcome in the audit log, and go on to the server's next."""
    change = int(row["id"])
    await ctx.db.execute(FINISH, ctx.guild.id, change, state, why, ctx.now)
    counts = await _counts(ctx, change)
    text = (
        f"Change {change}: {counts.get('changed', 0):,} changed, {counts.get('gone', 0):,} gone, "
        f"{counts.get('skipped', 0):,} skipped, {counts.get('pending', 0):,} not reached."
    )
    await ctx.record_outcome(int(row["grant_id"]), f"{text} {why}" if why else text, failed=state != "done")
    await ctx.db.execute(FORGET, ctx.guild.id, ctx.now - KEEP)
    async with ctx.db.transaction() as tx:
        await tx.schedule(run_change.bind(), at=ctx.now)


async def _claim(ctx: Ctx) -> Any | None:
    """The server's oldest unfinished change, claimed for one burst, with its next run queued already; or None."""
    async with ctx.db.transaction() as tx:
        row = await tx.fetchrow(OPEN, ctx.guild.id)
        if row is None:
            return None
        if row["next_at"] > ctx.now:
            await tx.schedule(run_change.bind(), at=row["next_at"])
            return None
        # A rule run takes the server's pace first, so a long change never holds up a promotion.
        busy: Any = await tx.fetchval(
            "SELECT busy_until FROM rule_pace WHERE guild_id = $1 AND busy_until > $2", ctx.guild.id, ctx.now
        )
        if busy is not None:
            await tx.schedule(run_change.bind(), at=busy)
            return None
        await tx.execute(CLAIM_IT, ctx.guild.id, row["id"], ctx.now + CLAIM, ctx.now)
        await tx.schedule(run_change.bind(), at=ctx.now + CLAIM)
    return row


async def _still_matching(ctx: Ctx, row: Any, role: Role, pending: list[int]) -> set[int]:
    """Which pending members the change still applies to, by the directory: its filter and the role condition."""
    base = (
        PeopleFilter.model_validate(json.loads(row["filter"])) if row["filter"] else PeopleFilter(bots=None)
    )
    narrowed = _with_role(base, role, bool(row["give"]))
    page = await ctx.members.find(narrowed, after=pending[0] - 1, limit=1000)
    found = {m.user_id for m in page}
    last = page[-1].user_id if len(page) == 1000 else None
    return {u for u in pending if u in found or (last is not None and u > last)}


async def _wait(ctx: Ctx, row: Any) -> None:
    async with ctx.db.transaction() as tx:
        await tx.execute(WAIT, ctx.guild.id, row["id"], ctx.now + RETRY)
        await tx.schedule(run_change.bind(), at=ctx.now + RETRY)


@plugin.job
async def run_change(ctx: Ctx) -> None:
    """One short burst of the server's oldest unfinished role change."""
    row = await _claim(ctx)
    if row is None:
        return
    if row["state"] == "stopping":
        await _finish(ctx, row, "stopped", row["why"] or "Stopped.")
        return
    if row["progress_at"] is not None and row["progress_at"] < ctx.now - STALL:
        await _finish(ctx, row, "stopped", "Stalled: no progress for a day.")
        return
    try:
        await _burst(ctx, row)
    except NotAuthorized as stop:
        await _finish(ctx, row, "stopped", str(stop))
    except DirectoryUnavailable:
        await _wait(ctx, row)
    except ActionError as stop:
        await _finish(ctx, row, "stopped", str(stop))


async def _burst(ctx: Ctx, row: Any) -> None:
    actor = await ctx.authorized(int(row["grant_id"]))
    role = ctx.guild.get_role(int(row["role_id"]))
    if role is None:
        raise ActionError("The role was deleted.")
    if actor.via in TOKEN_DOORS and role.permissions & DANGEROUS:
        raise ActionError(
            f"{role.name} now grants a moderator's permission, which an AI assistant's change cannot give."
        )
    by = await ctx.guild.get_member(actor.user_id)
    if by is None:
        raise ActionError("The member who confirmed it has left the server.")
    give = bool(row["give"])
    pending = [int(r["user_id"]) for r in await ctx.db.fetch(PENDING, ctx.guild.id, row["id"], BURST)]
    if not pending:
        await _finish(ctx, row, "done", None)
        return
    matching = await _still_matching(ctx, row, role, pending)
    for user_id in pending:
        outcome = "skipped"
        if user_id in matching:
            try:
                if give:
                    await ctx.guild.add_role(user_id, role, by=by)
                else:
                    await ctx.guild.remove_role(user_id, role, by=by)
                outcome = "changed"
            except MemberGone:
                outcome = "gone"
        await ctx.db.execute(MARK, ctx.guild.id, row["id"], user_id, outcome)
    async with ctx.db.transaction() as tx:
        await tx.execute(PROGRESS, ctx.guild.id, row["id"], ctx.now, ctx.now + WINDOW)
        await tx.schedule(run_change.bind(), at=ctx.now + WINDOW)


# Following and undoing.


@plugin.action(risk=READ, needs="manage_roles")
async def list_changes(ctx: Ctx) -> list[Listed]:
    """The server's latest role changes to matching members, with how far each has got."""
    return await ctx.db.fetch(Listed, LISTED, ctx.guild.id)


@plugin.action(needs="manage_roles")
async def stop(ctx: Ctx, change: int) -> str:
    """Stop a role change between bursts. What it changed stays changed; roles.revert undoes it.

    Args:
        change: The change's number, as roles.list_changes shows it
    """
    who = f"Stopped by member {ctx.actor.user_id}."
    if await ctx.db.execute(STOP, ctx.guild.id, change, who) == "UPDATE 0":
        raise ActionError(f"There is no running change {change} here.")
    return f"Change {change} stops before its next burst."


async def _revert_target(ctx: Ctx, change: int) -> tuple[Role, bool, list[int]]:
    row = await ctx.db.fetchrow(ONE, ctx.guild.id, change)
    if row is None or row["state"] not in ("done", "stopped"):
        raise ActionError(f"There is no finished change {change} here to revert.")
    role = ctx.guild.get_role(int(row["role_id"]))
    if role is None:
        raise ActionError("That change's role was deleted.")
    ids = [int(r["user_id"]) for r in await ctx.db.fetch(CHANGED, ctx.guild.id, change)]
    return role, not bool(row["give"]), ids


@plugin.action(risk=DESTRUCTIVE, needs="manage_roles")
async def revert(ctx: Ctx, change: int) -> HandedOff:
    """Undo a finished role change, for the members it changed, within 30 days. A member who already had the role
    before counts as changed, so a revert can take away a role they had.

    Args:
        change: The change's number, as roles.list_changes shows it
    """
    role, give, ids = await _revert_target(ctx, change)
    await _assignable(ctx, role, give)
    if ctx.audit_id is None:
        raise ActionError("A revert runs from a confirmed plan.")
    async with ctx.db.transaction() as tx:
        new = await tx.fetchval(int, NEW_CHANGE, ctx.guild.id, role.id, give, None, ctx.audit_id, change)
        await tx.execute(NEW_MEMBERS, ctx.guild.id, new, ids)
        await tx.schedule(run_change.bind(), at=ctx.now)
    return HandedOff(
        id=str(new), text=f"Change {new} reverts change {change}, for {_plural(len(ids), 'member')}."
    )


@revert.plan
async def plan_revert(ctx: Ctx, change: int) -> Diff:
    role, give, ids = await _revert_target(ctx, change)
    await _assignable(ctx, role, give)
    notes = [
        f"{'Give' if give else 'Take'} {role.name} {'back to' if give else 'from'} {_plural(len(ids), 'member')} "
        f"change {change} changed.",
        *_dangerous_note(role),
    ]
    return Diff(
        entries=[DiffEntry(change=_verb(give), target=role.name, key=f"revert:{change}")], notes=notes
    )

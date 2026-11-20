"""Role rules (clan-links.md, part 2): within a scope, each member holds the role of the first step whose label they
have, and none of the rule's other roles.

- `roles.rule_add` makes a rule, or replaces one, after a plan of what it would change now. Confirming stores it,
  with the apply's audit row as its grant, and runs it, above its cap, since the plan showed that run.
- `roles.rules` lists them, and `roles.rule_remove` removes one. Members keep the roles they hold.
- The `run_rules` job works out each rule's difference and applies it member by member, in bursts paced with
  matching changes, which wait behind it. It runs a minute after a rule's labels or a scope's roles change, or a
  member joins, and once a day, when it also posts what the rules changed.

A rule states the end result, so it stores no changes, and a run that can't finish in a burst works the difference
out again in the next. A run that would change more members than the rule's cap changes nothing and posts once; a
later run within the cap goes through, and confirming the rule again lets a held run through.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
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
    DirectoryMember,
    DirectoryUnavailable,
    EmptyConfig,
    HandedOff,
    Member,
    MemberFilter,
    MemberGone,
    NotAuthorized,
    PeopleFilter,
    Role,
    RoleChange,
    Surface,
    UntrustedText,
)
from teabot.sdk.labels import MAX_LENGTH

from . import plugin

type Ctx = Context[EmptyConfig]

STEPS_MAX = 25
CAP_MAX = 1000
# Discord allows 10 role changes per 10 seconds in a server (S10); a burst makes 8, leaving 2 for pickers.
BURST = 8
WINDOW = timedelta(seconds=10)
SETTLE = timedelta(minutes=1)
PAGE = 1000
# A run this much larger than its plan is refused, as a matching change's is.
GROWTH = 1.1
SHOWN = 10
TOKEN_DOORS = frozenset({"mcp", "service"})

RULE = """
SELECT id, scope, roles, labels, cap, grant_id, state, why, approved, held, running, handled, changed_today,
       last_run_at
FROM rules WHERE guild_id = $1
"""
OWNER = "SELECT id FROM rules WHERE guild_id = $1 AND $2 = ANY(roles) AND id IS DISTINCT FROM $3 LIMIT 1"
OFFERED_ANYWHERE = "SELECT EXISTS (SELECT 1 FROM offers WHERE guild_id = $1 AND role_id = ANY($2::bigint[]))"
NEW_RULE = """
INSERT INTO rules (guild_id, scope, roles, labels, cap, grant_id, approved) VALUES ($1, $2, $3, $4, $5, $6, $7)
RETURNING id
"""
REPLACE_RULE = """
UPDATE rules SET scope = $3, roles = $4, labels = $5, cap = $6, grant_id = $7, approved = $8, state = 'on',
    why = NULL, held = false, running = false, handled = '{}'
WHERE guild_id = $1 AND id = $2
"""
DUE = """
INSERT INTO rule_pace (guild_id, due_at) VALUES ($1, $2)
ON CONFLICT (guild_id) DO UPDATE SET due_at = $2
WHERE rule_pace.due_at IS NULL OR rule_pace.due_at < $3
RETURNING (SELECT busy_until FROM rule_pace WHERE guild_id = $1) AS busy_until
"""


class Rule(BaseModel):
    id: int
    scope: str
    roles: list[int]
    labels: list[str]
    cap: int | None
    grant_id: int
    state: str
    why: str | None
    approved: int | None
    held: bool
    running: bool
    handled: list[int]
    changed_today: int
    last_run_at: datetime | None

    @property
    def filter(self) -> PeopleFilter:
        return PeopleFilter.model_validate(json.loads(self.scope))


class Listed(BaseModel):
    id: int
    steps: list[str]
    scope: str
    cap: str
    state: str
    why: UntrustedText | None
    last_run_at: datetime | None

    def render(self) -> str:
        state = self.state if self.why is None else f"{self.state}: {self.why}"
        ran = f", last ran {self.last_run_at:%Y-%m-%d %H:%M}" if self.last_run_at else ""
        return f"Rule {self.id} ({state}{ran}), within {self.scope}, cap {self.cap}: {'; '.join(self.steps)}"


@dataclass(frozen=True)
class Change:
    """What a rule's run does to one member."""

    user_id: int
    name: str
    give: tuple[int, ...]
    take: tuple[int, ...]


def _plural(n: int, one: str) -> str:
    return f"{n:,} {one}" if n == 1 else f"{n:,} {one}s"


def default_cap(holders: int) -> int:
    """How many members a run may change unconfirmed: a tenth of the rule's holders, from 3 to 25."""
    return min(25, max(3, holders // 10))


async def _all(ctx: Ctx, *filters: MemberFilter) -> list[DirectoryMember]:
    found: list[DirectoryMember] = []
    after = 0
    while True:
        page = await ctx.members.find(*filters, after=after, limit=PAGE)
        found.extend(page)
        if len(page) < PAGE:
            return found
        after = page[-1].user_id


async def _holders(ctx: Ctx, roles: Sequence[int]) -> int:
    """How many present members hold one of the roles, ten roles to a query, as a filter takes."""
    ids: set[int] = set()
    for start in range(0, len(roles), 10):
        ids |= {m.user_id for m in await _all(ctx, MemberFilter(roles_any=list(roles[start : start + 10])))}
    return len(ids)


async def differences(
    ctx: Ctx, scope: PeopleFilter, roles: Sequence[int], labels: Sequence[str], skip: Sequence[int] = ()
) -> list[Change]:
    """Each member in scope whose roles differ from the rule's: the role of their first matching step, which they
    lack, and every other role of the rule, which they hold."""
    first: dict[int, int] = {}
    for role, label in zip(roles, labels, strict=True):
        step = MemberFilter(labels_from=scope.labels_from, labels_any=[label])
        for m in await _all(ctx, scope, step):
            first.setdefault(m.user_id, role)
    ruled, skipped = set(roles), set(skip)
    out: list[Change] = []
    for m in await _all(ctx, scope):
        if m.user_id in skipped:
            continue
        held = ruled & set(m.role_ids)
        want = first.get(m.user_id)
        give = (want,) if want is not None and want not in held else ()
        take = tuple(sorted(held - {want}))
        if give or take:
            out.append(Change(m.user_id, m.display_name, give, take))
    return out


def _role_name(ctx: Ctx, role_id: int) -> str:
    role = ctx.guild.get_role(role_id)
    return role.name if role is not None else str(role_id)


def _describe(ctx: Ctx, change: Change) -> str:
    parts = [f"gains {_role_name(ctx, r)}" for r in change.give] + [
        f"loses {_role_name(ctx, r)}" for r in change.take
    ]
    return f"{change.name} {', '.join(parts)}"


def _scope_words(scope: MemberFilter) -> str:
    parts: list[str] = []
    if scope.labels_any:
        parts.append(f"{scope.labels_from} labels {' or '.join(scope.labels_any)}")
    if scope.labels_all:
        parts.append(f"{scope.labels_from} labels {' and '.join(scope.labels_all)}")
    if scope.roles_any:
        parts.append("roles " + " or ".join(f"<@&{r}>" for r in scope.roles_any))
    if scope.roles_all:
        parts.append("roles " + " and ".join(f"<@&{r}>" for r in scope.roles_all))
    if scope.roles_none:
        parts.append("none of " + ", ".join(f"<@&{r}>" for r in scope.roles_none))
    return "members with " + ", ".join(parts) if parts else "every member"


def _refusal(ctx: Ctx, role: Role, by: Member) -> str | None:
    """Why a rule may not own this role, on every door, since a rule acts on outside data with no member
    confirming each run; else None."""
    if role.id == ctx.guild.id:
        return "A rule cannot give @everyone."
    if risky := sorted(role.permissions & DANGEROUS):
        words = ", ".join(p.replace("_", " ").title() for p in risky)
        return f"{role.name} grants {words}, so a rule cannot own it."
    return ctx.guild.can_assign(role, by=by) or ctx.guild.can_assign(role, by=by, give=False)


async def _confirmer(ctx: Ctx) -> Member:
    member = await ctx.guild.get_member(ctx.actor.user_id)
    if member is None:
        raise ActionError("You are not in this server.")
    return member


async def _checked(
    ctx: Ctx, roles: list[Role], labels: list[str], scope: PeopleFilter, rule: int | None
) -> None:
    """Every rule for a rule's definition, or `ActionError` saying which it breaks."""
    if len(roles) != len(labels):
        raise ActionError(
            "Give one label for each role: a member holds the role of the first label they have."
        )
    if len({r.id for r in roles}) != len(roles):
        raise ActionError("Each role appears once in a rule.")
    if scope.labels_from is None or not (scope.labels_any or scope.labels_all):
        raise ActionError(
            "A rule's scope needs labels_from with labels_any or labels_all, such as labels_any: [linked], so a "
            "plugin whose labels go stale empties the scope instead of taking roles from everyone."
        )
    if rule is not None and await ctx.db.fetchval(RULE + " AND id = $2", ctx.guild.id, rule) is None:
        raise ActionError(f"There is no rule {rule} here. /roles rules lists them.")
    by = await _confirmer(ctx)
    for role in roles:
        if why := _refusal(ctx, role, by):
            raise ActionError(why)
        if (owner := await ctx.db.fetchval(OWNER, ctx.guild.id, role.id, rule)) is not None:
            raise ActionError(f"{role.name} belongs to rule {owner}. Change that rule with rule:{owner}.")
    if await ctx.db.fetchval(bool, OFFERED_ANYWHERE, ctx.guild.id, [r.id for r in roles]):
        raise ActionError(
            "A role picker offers one of these roles, which a rule would undo. Take it off first."
        )


Roles = Annotated[list[Role], Field(min_length=1, max_length=STEPS_MAX)]
Labels = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=MAX_LENGTH)]], Field(max_length=STEPS_MAX)
]
Cap = Annotated[int, Field(ge=1, le=CAP_MAX)]
RULES = Surface.MCP | Surface.SERVICE | Surface.WEB


def _key(roles: list[Role], labels: list[str], scope: PeopleFilter, cap: int | None, rule: int | None) -> str:
    return json.dumps(
        {
            "roles": [[r.id, sorted(r.permissions), r.position] for r in roles],
            "labels": labels,
            "scope": scope.model_dump(mode="json"),
            "cap": cap,
            "rule": rule,
        },
        sort_keys=True,
    )


@plugin.action(risk=DESTRUCTIVE, needs=("manage_roles", "manage_guild"), surfaces=RULES)
async def rule_add(
    ctx: Ctx,
    roles: Roles,
    labels: Labels,
    scope: PeopleFilter,
    cap: Cap | None = None,
    rule: int | None = None,
) -> HandedOff:
    """Make a role rule: within the scope, each member holds the role of the first label they have, and none of
    the rule's other roles. It runs when labels change, and daily.

    Args:
        roles: The rule's roles, highest first
        labels: A label for each role, from the scope's labels_from
        cap: How many members a run may change before it waits for an admin
        rule: A rule to replace, by its number
    """
    await _checked(ctx, roles, labels, scope, rule)
    if ctx.audit_id is None:
        raise ActionError("A rule is made from a confirmed plan.")
    ids, words = [r.id for r in roles], list(labels)
    found = await differences(ctx, scope, ids, words)
    planned = _planned(ctx.diff)
    if planned is not None and len(found) > max(planned * GROWTH, planned + 5):
        raise ActionError(
            f"The rule would now change {_plural(len(found), 'member')}. Plan it again to see who it changes."
        )
    async with ctx.db.transaction() as tx:
        if rule is None:
            made = await tx.fetchval(
                int,
                NEW_RULE,
                ctx.guild.id,
                scope.model_dump_json(),
                ids,
                words,
                cap,
                ctx.audit_id,
                len(found),
            )
        else:
            await tx.execute(
                REPLACE_RULE,
                ctx.guild.id,
                rule,
                scope.model_dump_json(),
                ids,
                words,
                cap,
                ctx.audit_id,
                len(found),
            )
            made = rule
        await tx.schedule(run_rules.bind(), at=ctx.now)
    return HandedOff(
        id=str(made),
        text=f"Rule {made} is on, and changes {_plural(len(found), 'member')} now. /roles rules lists it.",
    )


@rule_add.plan
async def plan_rule_add(
    ctx: Ctx,
    roles: Roles,
    labels: Labels,
    scope: PeopleFilter,
    cap: Cap | None = None,
    rule: int | None = None,
) -> Diff:
    await _checked(ctx, roles, labels, scope, rule)
    ids = [r.id for r in roles]
    found = await differences(ctx, scope, ids, labels)
    gains = sum(1 for c in found if c.give)
    limit = cap or default_cap(await _holders(ctx, ids))
    steps = ", then ".join(f"{r.name} on {label}" for r, label in zip(roles, labels, strict=True))
    notes = [
        f"Within {_scope_words(scope)}: {steps}.",
        f"{_plural(len(found), 'member')} change now. {gains:,} gain a role, and the rest lose one.",
        f"Later runs change at most {_plural(limit, 'member')} each before they wait for an admin; confirming "
        "this runs it whatever its size.",
        "The rule undoes changes to its roles made by hand, by other bots, or by roles.give and roles.take.",
    ]
    if found:
        notes.append("Among the first: " + "; ".join(_describe(ctx, c) for c in found[:SHOWN]))
    if ctx.actor.via in TOKEN_DOORS:
        notes.append(
            "The rule stops if the token that confirms it expires or is revoked. One made on the site does not."
        )
    entry = DiffEntry(
        change="rule",
        target=f"rule {rule}" if rule else "new rule",
        key=_key(roles, labels, scope, cap, rule),
    )
    return Diff(entries=[entry], notes=notes)


def _planned(diff: Diff) -> int | None:
    for note in diff.notes:
        head = note.split(" ", 1)[0].replace(",", "")
        if head.isdigit() and " change now." in note:
            return int(head)
    return None


@plugin.action(risk=READ, needs="manage_roles")
async def rules(ctx: Ctx) -> list[Listed]:
    """The server's role rules, with their steps, scope and last run."""
    found = await ctx.db.fetch(Rule, RULE + " ORDER BY id", ctx.guild.id)
    return [
        Listed(
            id=r.id,
            steps=[
                f"{_role_name(ctx, role)} on {label}" for role, label in zip(r.roles, r.labels, strict=True)
            ],
            scope=_scope_words(r.filter),
            cap=str(r.cap) if r.cap else "a tenth of holders, 3 to 25",
            state=r.state,
            why=r.why,
            last_run_at=r.last_run_at,
        )
        for r in found
    ]


@plugin.action(needs="manage_roles")
async def rule_remove(ctx: Ctx, rule: int) -> str:
    """Remove a role rule. Members keep the roles they hold.

    Args:
        rule: The rule's number, as roles.rules shows it
    """
    if (
        await ctx.db.execute("DELETE FROM rules WHERE guild_id = $1 AND id = $2", ctx.guild.id, rule)
        == "DELETE 0"
    ):
        raise ActionError(f"There is no rule {rule} here.")
    return f"Removed rule {rule}. Members keep the roles they hold."


async def ruled_by(ctx: Ctx, role: Role) -> int | None:
    """The rule that owns a role, if one does."""
    return await ctx.db.fetchval(OWNER, ctx.guild.id, role.id, None)


# When rules run.


async def due(ctx: Ctx) -> None:
    """Run the server's rules a minute from now, unless a run is already pending or under way, so a busy label or
    role can't keep pushing the run back."""
    async with ctx.db.transaction() as tx:
        if not await tx.fetchval(
            bool, "SELECT EXISTS (SELECT 1 FROM rules WHERE guild_id = $1 AND state = 'on')", ctx.guild.id
        ):
            return
        at = ctx.now + SETTLE
        row = await tx.fetchrow(DUE, ctx.guild.id, at, ctx.now)
        if row is None:
            return
        busy = row["busy_until"]
        if busy is None or busy <= ctx.now:
            await tx.schedule(run_rules.bind(), at=at)


@plugin.on_labels_changed
async def labels_changed(ctx: Ctx, plugin_id: str) -> None:
    named = await ctx.db.fetchval(
        bool,
        "SELECT EXISTS (SELECT 1 FROM rules WHERE guild_id = $1 AND state = 'on' AND scope->>'labels_from' = $2)",
        ctx.guild.id,
        plugin_id,
    )
    if named:
        await due(ctx)


@plugin.on_member_roles
async def member_roles(ctx: Ctx, change: RoleChange) -> None:
    """A scope's roles changing, such as Exempt, brings a run; a ruled role's own changes wait for the daily run,
    so a rule never fights another bot change by change."""
    touched = {*change.added, *change.removed}
    for r in await ctx.db.fetch(Rule, RULE + " AND state = 'on'", ctx.guild.id):
        scope = r.filter
        if touched & {*scope.roles_any, *scope.roles_all, *scope.roles_none}:
            await due(ctx)
            return


@plugin.on_member_join
async def member_join(ctx: Ctx, member: Member) -> None:
    await due(ctx)


@plugin.job(every=timedelta(days=1))
async def rules_daily(ctx: Ctx) -> None:
    """Post what each rule changed in the last day, and run them all, as a safety run."""
    for r in await ctx.db.fetch(Rule, RULE + " AND changed_today > 0", ctx.guild.id):
        await ctx.log(
            r.grant_id, f"Rule {r.id} changed {_plural(r.changed_today, 'member')} in the last day."
        )
        await ctx.db.execute(
            "UPDATE rules SET changed_today = 0 WHERE guild_id = $1 AND id = $2", ctx.guild.id, r.id
        )
    await due(ctx)


# The run.


async def _stop(ctx: Ctx, r: Rule, why: str) -> None:
    await ctx.db.execute(
        "UPDATE rules SET state = 'stopped', why = $3, running = false, handled = '{}' WHERE guild_id = $1 AND id = $2",
        ctx.guild.id,
        r.id,
        why,
    )
    await ctx.log(
        r.grant_id,
        f"Rule {r.id} stopped: {why} An admin renews it with roles.rule_add and rule:{r.id}.",
        failed=True,
    )


async def _by(ctx: Ctx, r: Rule) -> tuple[Member, list[Role]]:
    """Who the rule acts for, and its roles, once its grant and every role still pass; else `ActionError`."""
    actor = await ctx.authorized(r.grant_id)
    by = await ctx.guild.get_member(actor.user_id)
    if by is None:
        raise ActionError("The member who confirmed it has left the server.")
    found: list[Role] = []
    for role_id in r.roles:
        role = ctx.guild.get_role(role_id)
        if role is None:
            raise ActionError(f"Role {role_id} was deleted.")
        if why := _refusal(ctx, role, by):
            raise ActionError(why)
        found.append(role)
    return by, found


async def _apply(
    ctx: Ctx, changes: list[Change], roles: dict[int, Role], by: Member, budget: int
) -> tuple[int, list[int]]:
    """Change members in turn, giving and taking together, within `budget` role changes; how many it used, and
    the members it reached."""
    used, reached = 0, list[int]()
    for change in changes:
        cost = len(change.give) + len(change.take)
        if reached and used + cost > budget:
            break
        try:
            for role_id in change.give:
                await ctx.guild.add_role(change.user_id, roles[role_id], by=by)
            for role_id in change.take:
                await ctx.guild.remove_role(change.user_id, roles[role_id], by=by)
        except MemberGone:
            pass
        used += cost
        reached.append(change.user_id)
        if used >= budget:
            break
    return used, reached


async def _run_one(ctx: Ctx, r: Rule, budget: int) -> tuple[int, bool]:
    """One rule's share of a burst: role changes used, and whether its run is finished."""
    try:
        by, found = await _by(ctx, r)
    except (NotAuthorized, ActionError) as stop:
        await _stop(ctx, r, str(stop))
        return 0, True
    changes = await differences(ctx, r.filter, r.roles, r.labels, r.handled)
    if not r.running:
        if not changes:
            await ctx.db.execute(
                "UPDATE rules SET approved = NULL, held = false, last_run_at = $3 WHERE guild_id = $1 AND id = $2",
                ctx.guild.id,
                r.id,
                ctx.now,
            )
            return 0, True
        cap = r.cap or default_cap(await _holders(ctx, r.roles))
        if r.approved is None and len(changes) > cap:
            if not r.held:
                await ctx.log(
                    r.grant_id,
                    f"Rule {r.id} is held: it would change {_plural(len(changes), 'member')}, above its cap of {cap}. "
                    f"It goes ahead once a run is within the cap, or an admin confirms roles.rule_add with "
                    f"rule:{r.id} again.",
                )
                await ctx.db.execute(
                    "UPDATE rules SET held = true WHERE guild_id = $1 AND id = $2", ctx.guild.id, r.id
                )
            return 0, True
    used, reached = await _apply(ctx, changes, {role.id: role for role in found}, by, budget)
    finished = len(reached) == len(changes)
    await ctx.db.execute(
        """
        UPDATE rules SET running = NOT $3, held = false, changed_today = changed_today + $4,
            handled = CASE WHEN $3 THEN '{}' ELSE handled || $5::bigint[] END,
            approved = CASE WHEN $3 THEN NULL ELSE approved END,
            last_run_at = CASE WHEN $3 THEN $6 ELSE last_run_at END
        WHERE guild_id = $1 AND id = $2
        """,
        ctx.guild.id,
        r.id,
        finished,
        len(reached),
        reached,
        ctx.now,
    )
    return used, finished


@plugin.job
async def run_rules(ctx: Ctx) -> None:
    """One burst of the server's rules, in order: each works out its difference and applies it until the burst's
    changes are spent, and the burst queues the next when a run is unfinished."""
    await ctx.db.execute("UPDATE rule_pace SET due_at = NULL WHERE guild_id = $1", ctx.guild.id)
    budget, more = BURST, False
    try:
        for r in await ctx.db.fetch(Rule, RULE + " AND state = 'on' ORDER BY id", ctx.guild.id):
            used, finished = await _run_one(ctx, r, budget)
            budget -= used
            if not finished:
                more = True
                break
            if budget <= 0:
                more = True
                break
    except DirectoryUnavailable:
        more = True
    async with ctx.db.transaction() as tx:
        busy = ctx.now + WINDOW if more else None
        pending: Any = await tx.fetchval(
            "INSERT INTO rule_pace (guild_id, busy_until) VALUES ($1, $2) "
            "ON CONFLICT (guild_id) DO UPDATE SET busy_until = $2 RETURNING due_at",
            ctx.guild.id,
            busy,
        )
        if busy is not None:
            await tx.schedule(run_rules.bind(), at=busy)
        elif pending is not None:
            # A trigger that came during this burst found it busy, so it is run now.
            await tx.schedule(run_rules.bind(), at=max(pending, ctx.now))


async def busy_until(ctx: Ctx) -> datetime | None:
    """When the server's rule run gives the pace back, while one is under way."""
    found: Any = await ctx.db.fetchval("SELECT busy_until FROM rule_pace WHERE guild_id = $1", ctx.guild.id)
    return found if found is not None and found > ctx.now else None

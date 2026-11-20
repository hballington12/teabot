"""Role rules: within a scope, each member holds the role of the first step whose label they have, and none of the
rule's other roles; a run above its cap waits for an admin, and a rule stops when its grant ends."""

import json
from datetime import timedelta
from typing import Any

import discord

from teabot.core.plans import Planned
from teabot.core.registry import Call
from teabot.plugins.roles import plugin
from teabot.plugins.roles.rules import rules_daily, run_rules
from teabot.sdk import Actor
from teabot.testing import FakeChannel, FakeMember, FakeRole, HarnessFactory, PluginHarness

ADMIN = discord.Permissions(manage_roles=True, manage_guild=True)
NONE = discord.Permissions.none()
SOURCE = "clan"


class Server:
    """A server whose `clan` plugin labels members, with a ladder of three rank roles below a moderator."""

    def __init__(self, harness: PluginHarness) -> None:
        self.harness = harness
        self.db: Any = harness.admin
        guild = harness.guild
        self.bronze = guild.add_role("Bronze", position=2)
        self.silver = guild.add_role("Silver", position=3)
        self.gold = guild.add_role("Gold", position=4)
        self.exempt = guild.add_role("Exempt", position=5)
        harness.member.guild_permissions = ADMIN
        harness.member.roles = [guild.add_role("Mod", position=10)]
        self.members: list[FakeMember] = []

    async def start(self) -> None:
        guild = self.harness.guild.id
        self.harness.registry.labels.fresh_for[SOURCE] = timedelta(days=1)  # pyright: ignore[reportOptionalMemberAccess]
        await self.db.execute(
            "INSERT INTO core.guild_plugins (guild_id, plugin_id, enabled) VALUES ($1, $2, true)",
            guild,
            SOURCE,
        )
        await self.db.execute(
            "INSERT INTO core.label_state (guild_id, plugin_id, as_of, written_at) VALUES ($1, $2, now(), now())",
            guild,
            SOURCE,
        )
        await self.db.execute(
            "INSERT INTO core.directory_state (guild_id, backfilled) VALUES ($1, true)", guild
        )
        await self.sync()

    def add(self, name: str, labels: list[str], roles: list[FakeRole] | None = None) -> FakeMember:
        member = self.harness.guild.add_member(NONE, name=name, roles=roles or [], cached=False)
        self.members.append(member)
        member.labels = labels  # pyright: ignore[reportAttributeAccessIssue]
        return member

    async def sync(self) -> None:
        """The directory's copy of the server, and the clan plugin's labels, as they are now."""
        guild = self.harness.guild.id
        for m in [self.harness.member, *self.members]:
            await self.db.execute(
                "INSERT INTO core.members (guild_id, user_id, name, role_ids, observed_at) "
                "VALUES ($1, $2, $3, $4, now()) ON CONFLICT (guild_id, user_id) DO UPDATE SET role_ids = $4",
                guild,
                m.id,
                m.name,
                [r.id for r in m.roles],
            )
        for m in self.members:
            labels = getattr(m, "labels", [])
            await self.db.execute(
                "INSERT INTO core.member_labels (guild_id, plugin_id, user_id, labels) VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (guild_id, plugin_id, user_id) DO UPDATE SET labels = $4",
                guild,
                SOURCE,
                m.id,
                labels,
            )

    def ladder(self, **extra: Any) -> dict[str, Any]:
        return {
            "roles": [str(self.gold.id), str(self.silver.id), str(self.bronze.id)],
            "labels": ["tenure:gold", "tenure:silver", "tenure:bronze"],
            "labels_from": SOURCE,
            "labels_any": ["linked"],
            "roles_none": [str(self.exempt.id)],
        } | extra

    async def call(self, action: str, raw: dict[str, Any], via: str = "web") -> Any:
        actor = Actor(self.harness.member.id, via, None)  # pyright: ignore[reportArgumentType]
        return await self.harness.registry.invoke(Call(action, self.harness.guild.id, actor, raw))

    async def confirmed(self, raw: dict[str, Any]) -> Planned:
        plan = await self.call("roles.rule_add", raw)
        assert isinstance(plan, Planned)
        await self.call("roles.rule_add", raw | {"confirm": plan.confirm})
        await self.finish()
        return plan

    async def finish(self) -> None:
        """Run the rules' bursts to the end, ten seconds apart, keeping the directory in step."""
        for _ in range(10):
            await self.harness.run_jobs()
            await self.sync()
            await self.harness.advance(seconds=11)
        await self.harness.run_jobs()

    async def lines(self) -> list[str]:
        rows = await self.db.fetch(
            "SELECT input FROM core.audit_log WHERE action = 'roles.rule_add' AND input ? 'grant' ORDER BY id"
        )
        return [json.loads(r["input"])["outcome"] for r in rows]


async def server(teabot_harness: HarnessFactory) -> Server:
    found = Server(await teabot_harness(plugin))
    return found


def held(member: FakeMember) -> set[str]:
    return {r.name for r in member.roles}


async def test_a_rule_gives_each_member_the_first_step_they_match_and_takes_the_rest(
    teabot_harness: HarnessFactory,
) -> None:
    s = await server(teabot_harness)
    ann = s.add("ann", ["linked", "tenure:silver"], [s.bronze])
    bob = s.add("bob", ["linked", "tenure:gold", "tenure:silver"])
    cat = s.add("cat", ["linked"], [s.gold])
    dan = s.add("dan", [], [s.gold])
    eve = s.add("eve", ["linked", "tenure:bronze"], [s.exempt, s.gold])
    await s.start()
    plan = await s.call("roles.rule_add", s.ladder())
    assert isinstance(plan, Planned)
    assert plan.notes[1].startswith("3 members change now.")
    await s.call("roles.rule_add", s.ladder() | {"confirm": plan.confirm})
    await s.finish()
    assert held(ann) == {"Silver"}
    assert held(bob) == {"Gold"}
    # Linked with no step's label: none of the rule's roles. Outside the scope, or exempt: left alone.
    assert held(cat) == set()
    assert held(dan) == {"Gold"}
    assert held(eve) == {"Exempt", "Gold"}
    [listed] = (await s.call("roles.rules", {})).items
    assert listed.steps == ["Gold on tenure:gold", "Silver on tenure:silver", "Bronze on tenure:bronze"]


async def test_a_run_above_its_cap_is_held_once_and_goes_ahead_within_it(
    teabot_harness: HarnessFactory,
) -> None:
    s = await server(teabot_harness)
    first = s.add("first", ["linked", "tenure:bronze"])
    await s.start()
    await s.confirmed(s.ladder(cap=1))
    assert held(first) == {"Bronze"}
    promoted = [s.add(f"m{i}", ["linked", "tenure:silver"]) for i in range(3)]
    await s.sync()
    await s.harness.run_job(run_rules.bind())
    await s.harness.run_job(run_rules.bind())
    assert all(held(m) == set() for m in promoted)
    assert (await s.lines()) == [
        "Rule 1 is held: it would change 3 members, above its cap of 1. It goes ahead once a run is within the "
        "cap, or an admin confirms roles.rule_add with rule:1 again."
    ]
    for m in promoted[1:]:
        m.labels = ["linked"]  # pyright: ignore[reportAttributeAccessIssue]
    await s.sync()
    await s.harness.run_job(run_rules.bind())
    assert held(promoted[0]) == {"Silver"}


async def test_a_held_run_goes_through_when_the_rule_is_confirmed_again(
    teabot_harness: HarnessFactory,
) -> None:
    s = await server(teabot_harness)
    s.add("first", ["linked", "tenure:bronze"])
    await s.start()
    await s.confirmed(s.ladder(cap=1))
    promoted = [s.add(f"m{i}", ["linked", "tenure:gold"]) for i in range(12)]
    await s.sync()
    await s.harness.run_job(run_rules.bind())
    assert all(held(m) == set() for m in promoted)
    await s.confirmed(s.ladder(cap=1, rule=1))
    assert all(held(m) == {"Gold"} for m in promoted)


async def test_the_daily_run_posts_what_each_rule_changed(teabot_harness: HarnessFactory) -> None:
    s = await server(teabot_harness)
    s.add("ann", ["linked", "tenure:gold"])
    s.add("bob", ["linked", "tenure:bronze"])
    await s.start()
    await s.confirmed(s.ladder())
    await s.harness.run_job(rules_daily.bind())
    assert (await s.lines()) == ["Rule 1 changed 2 members in the last day."]


async def test_a_rule_stops_when_its_confirmer_loses_manage_roles(teabot_harness: HarnessFactory) -> None:
    s = await server(teabot_harness)
    ann = s.add("ann", ["linked", "tenure:gold"])
    await s.start()
    await s.confirmed(s.ladder())
    ann.labels = ["linked", "tenure:silver"]  # pyright: ignore[reportAttributeAccessIssue]
    await s.sync()
    s.harness.member.guild_permissions = NONE
    await s.harness.run_job(run_rules.bind())
    assert held(ann) == {"Gold"}
    [line] = await s.lines()
    assert line.startswith("Rule 1 stopped:")
    s.harness.member.guild_permissions = ADMIN
    [listed] = (await s.call("roles.rules", {})).items
    assert listed.state == "stopped"


async def test_a_rule_refuses_a_scope_without_labels_and_a_role_a_picker_offers(
    teabot_harness: HarnessFactory,
) -> None:
    s = await server(teabot_harness)
    await s.start()
    for raw, said in (
        (s.ladder(labels_any=[]), "needs labels_from with labels_any or labels_all"),
        (s.ladder(labels=["tenure:gold"]), "one label for each role"),
    ):
        try:
            await s.call("roles.rule_add", raw)
        except Exception as refused:
            assert said in str(refused)
        else:
            raise AssertionError(f"expected a refusal: {said}")
    channel = s.harness.guild.add_channel(FakeChannel())
    await s.call(
        "roles.post", {"channel": str(channel.id), "title": "Pick", "roles": [str(s.bronze.id)]}, "slash"
    )
    try:
        await s.call("roles.rule_add", s.ladder())
    except Exception as refused:
        assert "A role picker offers" in str(refused)
    else:
        raise AssertionError("expected a refusal")


async def test_a_ruled_role_is_refused_by_a_picker_and_named_in_a_give_plan(
    teabot_harness: HarnessFactory,
) -> None:
    s = await server(teabot_harness)
    ann = s.add("ann", ["linked"])
    await s.start()
    await s.confirmed(s.ladder())
    channel = s.harness.guild.add_channel(FakeChannel())
    try:
        await s.call(
            "roles.post", {"channel": str(channel.id), "title": "Pick", "roles": [str(s.gold.id)]}, "slash"
        )
    except Exception as refused:
        assert "Rule 1 owns Gold" in str(refused)
    else:
        raise AssertionError("expected a refusal")
    plan = await s.call("roles.give", {"role": str(s.gold.id), "members": [str(ann.id)]})
    assert isinstance(plan, Planned)
    assert "Rule 1 owns Gold, and undoes this change on its next run." in plan.notes

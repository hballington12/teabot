"""The audit log (WP2.4, D24): every call recorded, changes posted, retention by partition."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import discord
import pytest

from teapot.core.audit import POST_ATTEMPTS, AuditLog, AuditMaintenance, PostAudit, ensure_read_partitions
from teapot.core.queue import Queue
from teapot.core.registry import CallRecord
from teapot.core.worker import Workers
from teapot.db.migrate import migrate
from teapot.db.naming import Naming
from teapot.db.pool import Pools
from teapot.db.types import Conn
from teapot.sdk import Actor, Risk

GUILD, CHANNEL = 1001, 3001


def record(action: str = "alpha.add", risk: Risk = Risk.WRITE) -> CallRecord:
    return CallRecord(action, GUILD, Actor(2001, "slash"), {"name": "x"}, risk)


@dataclass
class FakeChannel:
    sent: list[discord.Embed] = field(default_factory=list[discord.Embed])

    async def send(self, *, embed: discord.Embed) -> None:
        self.sent.append(embed)


@dataclass
class FakeClient:
    channels: dict[int, FakeChannel]

    def get_channel(self, channel_id: int) -> FakeChannel | None:
        return self.channels.get(channel_id)


@pytest.fixture
async def queue(admin: Conn, naming: Naming, pools: Pools) -> Queue:
    await migrate(admin, naming, [])
    return Queue(pools.core_db())


async def test_a_change_is_recorded_before_and_after_and_its_post_queued(queue: Queue, admin: Conn) -> None:
    audit = AuditLog(queue)
    audit_id = await audit.started(record())
    row = await admin.fetchrow(
        "SELECT outcome, action, user_id, surface, input FROM core.audit_log WHERE id = $1", audit_id
    )
    assert row is not None and (row["outcome"], row["action"], row["user_id"], row["surface"]) == (
        "started",
        "alpha.add",
        2001,
        "slash",
    )
    assert json.loads(row["input"]) == {"name": "x"}
    await audit.finished(audit_id, "error", "RuntimeError('x')")
    done = await admin.fetchrow("SELECT outcome, error FROM core.audit_log WHERE id = $1", audit_id)
    assert done is not None and (done["outcome"], done["error"]) == ("error", "RuntimeError('x')")
    jobs = await admin.fetch("SELECT handler, guild_id, payload FROM core.jobs WHERE handler = 'post_audit'")
    assert [(j["guild_id"], json.loads(j["payload"])) for j in jobs] == [(GUILD, {"audit_id": audit_id})]


async def test_a_read_gets_one_row_in_the_reads_table_and_no_post(queue: Queue, admin: Conn) -> None:
    await AuditLog(queue).single(record("alpha.count", Risk.READ), "ok", None)
    assert await admin.fetchval("SELECT count(*) FROM core.audit_reads WHERE action = 'alpha.count'") == 1
    assert await admin.fetchval("SELECT count(*) FROM core.audit_log") == 0
    assert await admin.fetchval("SELECT count(*) FROM core.jobs WHERE handler = 'post_audit'") == 0


async def test_a_refused_change_is_one_row_and_is_posted(queue: Queue, admin: Conn) -> None:
    await AuditLog(queue).single(record(), "refused", "forbidden")
    row = await admin.fetchrow("SELECT outcome, error FROM core.audit_log")
    assert row is not None and (row["outcome"], row["error"]) == ("refused", "forbidden")
    assert await admin.fetchval("SELECT count(*) FROM core.jobs WHERE handler = 'post_audit'") == 1


async def test_reads_land_in_their_day_partition_once_it_exists(queue: Queue, admin: Conn) -> None:
    today = datetime.now(UTC).date()
    await ensure_read_partitions(queue.db, today, days_ahead=2)
    await AuditLog(queue).single(record("alpha.count", Risk.READ), "ok", None)
    partition = await admin.fetchval("SELECT tableoid::regclass::text FROM core.audit_reads")
    assert partition == f"core.audit_reads_p{today:%Y%m%d}"


async def test_reads_without_a_day_partition_land_in_the_default_one(queue: Queue, admin: Conn) -> None:
    await AuditLog(queue).single(record("alpha.count", Risk.READ), "ok", None)
    assert (
        await admin.fetchval("SELECT tableoid::regclass::text FROM core.audit_reads")
        == "core.audit_reads_default"
    )


async def test_maintenance_keeps_partitions_ahead_and_drops_expired_ones(queue: Queue, admin: Conn) -> None:
    today = datetime.now(UTC).date()
    old = today - timedelta(days=31)
    await ensure_read_partitions(queue.db, old, days_ahead=0)
    await AuditMaintenance(queue.db, reads_days=30, changes_days=365).run(today)
    names = {
        r["relname"]
        for r in await admin.fetch(
            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
            "WHERE i.inhparent = 'core.audit_reads'::regclass"
        )
    }
    assert f"audit_reads_p{old:%Y%m%d}" not in names
    assert {f"audit_reads_p{today + timedelta(days=d):%Y%m%d}" for d in range(8)} <= names
    assert "audit_reads_default" in names


async def test_maintenance_trims_old_changes_and_old_default_reads(queue: Queue, admin: Conn) -> None:
    audit = AuditLog(queue)
    for age in (400, 10):
        audit_id = await audit.started(record())
        await admin.execute(
            "UPDATE core.audit_log SET time = now() - make_interval(days => $2) WHERE id = $1", audit_id, age
        )
    await audit.single(record("alpha.count", Risk.READ), "ok", None)
    await admin.execute("UPDATE core.audit_reads SET time = now() - interval '40 days'")
    await AuditMaintenance(queue.db, reads_days=30, changes_days=365, batch=1).run(datetime.now(UTC).date())
    assert await admin.fetchval("SELECT count(*) FROM core.audit_log") == 1
    assert await admin.fetchval("SELECT count(*) FROM core.audit_reads") == 0


async def set_log_channel(admin: Conn, channel_id: int) -> None:
    await admin.execute(
        "INSERT INTO core.guild_plugins (guild_id, plugin_id, enabled, config) VALUES ($1, 'admin', true, $2::jsonb)",
        GUILD,
        json.dumps({"log_channel_id": str(channel_id)}),
    )


async def run_posts(queue: Queue, client: FakeClient) -> None:
    queue.register("core", "post_audit", PostAudit(queue.db, client))
    workers = Workers(queue, lambda: ["core"])
    while await workers.run_once():
        pass


async def test_a_change_is_posted_to_the_log_channel_with_its_id(queue: Queue, admin: Conn) -> None:
    await set_log_channel(admin, CHANNEL)
    channel = FakeChannel()
    audit = AuditLog(queue)
    audit_id = await audit.started(record())
    await audit.finished(audit_id, "ok", None)
    await run_posts(queue, FakeClient({CHANNEL: channel}))
    (embed,) = channel.sent
    text = json.dumps(embed.to_dict())
    assert "alpha.add" in text and "<@2001>" in text and f"audit #{audit_id}" in text and "ok" in text
    fields = {f.name: f for f in embed.fields}
    assert "Error" not in fields
    assert fields["Input"].inline is False and fields["Member"].inline is True


async def test_a_failed_change_is_posted_with_its_error_full_width(queue: Queue, admin: Conn) -> None:
    await set_log_channel(admin, CHANNEL)
    channel = FakeChannel()
    audit = AuditLog(queue)
    await audit.finished(await audit.started(record()), "error", "RuntimeError('it broke')")
    await run_posts(queue, FakeClient({CHANNEL: channel}))
    (embed,) = channel.sent
    error = next(f for f in embed.fields if f.name == "Error")
    assert error.value == "RuntimeError('it broke')" and error.inline is False


async def test_a_refused_lookup_stays_in_the_reads_table_and_is_not_posted(queue: Queue, admin: Conn) -> None:
    await AuditLog(queue).single(record("alpha.count", Risk.READ), "refused", "forbidden")
    row = await admin.fetchrow("SELECT outcome, error FROM core.audit_reads")
    assert row is not None and (row["outcome"], row["error"]) == ("refused", "forbidden")
    assert await admin.fetchval("SELECT count(*) FROM core.audit_log") == 0
    assert await admin.fetchval("SELECT count(*) FROM core.jobs WHERE handler = 'post_audit'") == 0


@pytest.mark.parametrize("configured", [False, True], ids=["no log channel", "channel gone"])
async def test_nothing_is_posted_without_a_usable_log_channel(
    queue: Queue, admin: Conn, configured: bool
) -> None:
    if configured:
        await set_log_channel(admin, CHANNEL)
    audit = AuditLog(queue)
    await audit.finished(await audit.started(record()), "ok", None)
    await run_posts(queue, FakeClient({}))
    assert await admin.fetchval("SELECT state FROM core.jobs WHERE handler = 'post_audit'") == "done"


async def test_a_post_retries_for_over_a_day_so_an_outage_never_loses_it(queue: Queue, admin: Conn) -> None:
    audit = AuditLog(queue)
    await audit.finished(await audit.started(record()), "ok", None)
    attempts = await admin.fetchval("SELECT max_attempts FROM core.jobs WHERE handler = 'post_audit'")
    assert attempts == POST_ATTEMPTS
    hours = sum(min(2**n, 3600) for n in range(1, POST_ATTEMPTS)) / 3600
    assert hours > 24

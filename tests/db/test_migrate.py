"""The migration runner."""

import asyncio
from pathlib import Path
from typing import Any

import asyncpg
import pytest

from teabot.db.bootstrap import bootstrap
from teabot.db.migrate import CORE_MIGRATIONS, MigrationError, PluginMigrations, migrate, read_files
from teabot.db.naming import Naming
from teabot.db.pool import ConnectionInfo, Login, Pools, connect
from teabot.db.types import Conn

ENTRIES = "CREATE TABLE entries (guild_id bigint NOT NULL, name text);"


def write(directory: Path, files: dict[str, str]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, sql in files.items():
        (directory / name).write_text(sql)
    return directory


@pytest.fixture
async def ready(pools: Pools) -> Pools:
    """Bootstrapped roles, so the runner can grant to them."""
    return pools


async def test_core_and_plugin_migrate_in_order_once(
    admin: Conn, naming: Naming, ready: Pools, tmp_path: Path
) -> None:
    alpha = write(
        tmp_path / "alpha",
        {"0001_entries.sql": ENTRIES, "0002_seed.sql": "INSERT INTO entries VALUES (1, 'a');"},
    )
    report = await migrate(admin, naming, [PluginMigrations("alpha", alpha)])
    core_versions = [f.version for f in read_files(CORE_MIGRATIONS)]
    assert report.applied == {"core": core_versions, "alpha": [1, 2]} and not report.failed
    again = await migrate(admin, naming, [PluginMigrations("alpha", alpha)])
    assert again.applied == {"core": [], "alpha": []}
    assert await ready.plugin_db("alpha").fetchval("SELECT count(*) FROM entries") == 1


async def test_plugin_tables_are_owned_by_the_plugin_role(
    admin: Conn, naming: Naming, ready: Pools, tmp_path: Path
) -> None:
    await migrate(admin, naming, [PluginMigrations("alpha", write(tmp_path / "a", {"0001_e.sql": ENTRIES}))])
    owner = await admin.fetchval("SELECT tableowner FROM pg_tables WHERE schemaname = 'plugin_alpha'")
    assert owner == naming.plugin_role("alpha")


async def test_core_tables_are_usable_by_the_app_role(admin: Conn, naming: Naming, ready: Pools) -> None:
    await migrate(admin, naming, [])
    await ready.core_db().execute("INSERT INTO core.guilds (guild_id) VALUES ($1)", 1)
    assert await ready.core_db().fetchval("SELECT count(*) FROM core.guilds") == 1


async def test_failed_file_rolls_back_and_others_carry_on(
    admin: Conn, naming: Naming, ready: Pools, tmp_path: Path
) -> None:
    bad = write(
        tmp_path / "bad",
        {"0001_ok.sql": ENTRIES, "0002_broken.sql": "CREATE TABLE half (guild_id bigint); SELEC oops;"},
    )
    good = write(tmp_path / "good", {"0001_e.sql": ENTRIES})
    report = await migrate(admin, naming, [PluginMigrations("bad", bad), PluginMigrations("good", good)])
    assert "bad" in report.failed and report.applied["good"] == [1]
    tables = await admin.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'plugin_bad'")
    assert [t["tablename"] for t in tables] == ["entries"]


async def test_dollar_quoted_trigger(admin: Conn, naming: Naming, ready: Pools, tmp_path: Path) -> None:
    sql = (
        ENTRIES
        + """
CREATE FUNCTION upper_name() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.name := upper(NEW.name); RETURN NEW; END; $$;
CREATE TRIGGER upper_name BEFORE INSERT ON entries FOR EACH ROW EXECUTE FUNCTION upper_name();
"""
    )
    report = await migrate(
        admin, naming, [PluginMigrations("alpha", write(tmp_path / "a", {"0001_t.sql": sql}))]
    )
    assert not report.failed
    db = ready.plugin_db("alpha")
    await db.execute("INSERT INTO entries VALUES ($1, $2)", 1, "quiet")
    assert await db.fetchval("SELECT name FROM entries") == "QUIET"


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        ("CREATE TABLE notes (body text);", "without a bigint guild_id"),
        ("CREATE TABLE notes (guild_id integer);", "without a bigint guild_id"),
        ("CREATE TABLE core.sneaky (guild_id bigint);", "permission denied"),
        ("CREATE TABLE public.sneaky (guild_id bigint);", "permission denied"),
    ],
)
async def test_bad_migrations_are_refused(
    admin: Conn, naming: Naming, ready: Pools, tmp_path: Path, sql: str, message: str
) -> None:
    report = await migrate(
        admin, naming, [PluginMigrations("alpha", write(tmp_path / "a", {"0001_x.sql": sql}))]
    )
    assert message in report.failed["alpha"]
    assert not await admin.fetchval("SELECT count(*) FROM core.migrations WHERE plugin_id = 'alpha'")


async def test_downgrade_and_edited_files_are_refused(
    admin: Conn, naming: Naming, ready: Pools, tmp_path: Path
) -> None:
    alpha = write(
        tmp_path / "a", {"0001_e.sql": ENTRIES, "0002_more.sql": "ALTER TABLE entries ADD COLUMN n int;"}
    )
    await migrate(admin, naming, [PluginMigrations("alpha", alpha)])
    (alpha / "0002_more.sql").unlink()
    assert (
        "files stop at 1"
        in (await migrate(admin, naming, [PluginMigrations("alpha", alpha)])).failed["alpha"]
    )
    write(alpha, {"0002_more.sql": "ALTER TABLE entries ADD COLUMN m int;"})
    assert (
        "changed after it was applied"
        in (await migrate(admin, naming, [PluginMigrations("alpha", alpha)])).failed["alpha"]
    )


def test_file_names_and_gaps_are_checked(tmp_path: Path) -> None:
    with pytest.raises(MigrationError, match="NNNN_name"):
        read_files(write(tmp_path / "a", {"1_bad.sql": ""}))
    with pytest.raises(MigrationError, match="numbered"):
        read_files(write(tmp_path / "b", {"0001_a.sql": "", "0003_c.sql": ""}))


async def test_two_runners_migrate_once(
    owner_kwargs: dict[str, Any], naming: Naming, ready: Pools, tmp_path: Path
) -> None:
    slow = write(tmp_path / "a", {"0001_e.sql": ENTRIES + " SELECT pg_sleep(0.3);"})
    conns = [await asyncpg.connect(**owner_kwargs) for _ in range(2)]
    try:
        reports = await asyncio.gather(
            *(migrate(c, naming, [PluginMigrations("alpha", slow)]) for c in conns)
        )
    finally:
        for c in conns:
            await c.close()
    assert sorted(len(r.applied["alpha"]) for r in reports) == [0, 1]


async def test_schedule_job_queues_under_the_plugin_id(
    admin: Conn, naming: Naming, ready: Pools, tmp_path: Path
) -> None:
    await migrate(admin, naming, [PluginMigrations("alpha", write(tmp_path / "a", {"0001_e.sql": ENTRIES}))])
    db = ready.plugin_db("alpha")
    job_id = await db.fetchval("SELECT schedule_job($1, $2)", 7, "announce")
    row = await admin.fetchrow(
        "SELECT guild_id, plugin_id, handler, state FROM core.jobs WHERE id = $1", job_id
    )
    assert row is not None and dict(row) == {
        "guild_id": 7,
        "plugin_id": "alpha",
        "handler": "announce",
        "state": "pending",
    }
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await db.fetch("SELECT * FROM core.jobs")


async def test_a_plugin_without_migrations_still_gets_its_schema(
    admin: Conn, naming: Naming, ready: Pools
) -> None:
    report = await migrate(admin, naming, [PluginMigrations("bare", None)])
    assert report.applied["bare"] == [] and not report.failed
    assert await admin.fetchval("SELECT 1 FROM pg_namespace WHERE nspname = 'plugin_bare'") == 1


async def test_a_server_bound_handle_queues_for_its_server_with_an_empty_payload(
    admin: Conn, naming: Naming, ready: Pools, tmp_path: Path
) -> None:
    await migrate(admin, naming, [PluginMigrations("alpha", write(tmp_path / "a", {"0001_e.sql": ENTRIES}))])
    job_id = await ready.guild_plugin_db("alpha", 7).schedule("ping")
    row = await admin.fetchrow("SELECT guild_id, handler, payload FROM core.jobs WHERE id = $1", job_id)
    assert row is not None and (row["guild_id"], row["handler"], row["payload"]) == (7, "ping", "{}")


async def test_an_owner_that_is_not_a_superuser_migrates_a_plugin(
    admin: Conn, naming: Naming, owner_kwargs: dict[str, Any], info: ConnectionInfo, tmp_path: Path
) -> None:
    """Managed and carefully set up Postgres runs teabot under an owner without superuser rights. The owner
    holds each plugin role without inheriting it, so nothing it does in a plugin's schema may rely on that."""
    owner = f"{naming.prefix}_owner"
    database = owner_kwargs["database"]
    await admin.execute(f"CREATE ROLE \"{owner}\" LOGIN CREATEROLE PASSWORD 'o'")
    await admin.execute(f'ALTER DATABASE "{database}" OWNER TO "{owner}"')
    directory = tmp_path / "alpha"
    directory.mkdir()
    (directory / "0001_t.sql").write_text("CREATE TABLE entries (guild_id bigint);")
    try:
        conn = await connect(Login(info, owner, "o"))
        try:
            await bootstrap(conn, naming, "a", "p")
            report = await migrate(conn, naming, [PluginMigrations("alpha", directory)])
        finally:
            await conn.close()
        assert report.failed == {} and report.applied["alpha"] == [1]
        functions = await admin.fetchval(
            "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
            " WHERE n.nspname = 'plugin_alpha' AND p.proname = 'schedule_job' AND pg_get_userbyid(p.proowner) = $1",
            owner,
        )
        assert functions == 1
    finally:
        await admin.execute(f'ALTER DATABASE "{database}" OWNER TO "{owner_kwargs["user"]}"')

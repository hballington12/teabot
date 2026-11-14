"""Per-server plugin config (D8, D10): validated through the plugin's current model where it enters."""

import json

import pytest
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from teabot.core.config import ConfigError, ConfigStore
from teabot.db.migrate import migrate
from teabot.db.naming import Naming
from teabot.db.pool import Pools
from teabot.db.types import Conn
from teabot.sdk import ChannelRef

GUILD = 42


class GiveawayConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    channel_id: ChannelRef | None = None
    duration_minutes: int = Field(default=60, validation_alias=AliasChoices("duration_minutes", "minutes"))


@pytest.fixture
async def store(admin: Conn, naming: Naming, pools: Pools) -> ConfigStore:
    await migrate(admin, naming, [])
    return ConfigStore(pools.core_db())


async def stored(admin: Conn, raw: dict[str, object]) -> None:
    await admin.execute(
        "INSERT INTO core.guild_plugins (guild_id, plugin_id, config) VALUES ($1, 'giveaways', $2::jsonb)",
        GUILD,
        json.dumps(raw),
    )


async def test_a_server_with_nothing_stored_gets_the_defaults(store: ConfigStore) -> None:
    assert await store.load(GUILD, "giveaways", GiveawayConfig) == GiveawayConfig()


async def test_saved_config_loads_back_and_keeps_the_enabled_flag(store: ConfigStore, admin: Conn) -> None:
    await stored(admin, {})
    await admin.execute("UPDATE core.guild_plugins SET enabled = true")
    await store.save(GUILD, "giveaways", GiveawayConfig(channel_id=123456789012345678, duration_minutes=5), 7)
    assert await store.load(GUILD, "giveaways", GiveawayConfig) == GiveawayConfig(
        channel_id=123456789012345678, duration_minutes=5
    )
    row = await admin.fetchrow("SELECT enabled, updated_by, config FROM core.guild_plugins")
    assert row is not None and row["enabled"] is True and row["updated_by"] == 7
    assert json.loads(row["config"])["channel_id"] == "123456789012345678"


async def test_a_renamed_field_reads_old_data_and_a_removed_one_is_ignored(
    store: ConfigStore, admin: Conn
) -> None:
    await stored(admin, {"minutes": 15, "colour": "red"})
    assert await store.load(GUILD, "giveaways", GiveawayConfig) == GiveawayConfig(duration_minutes=15)


async def test_stored_config_the_model_refuses_is_an_error_naming_plugin_and_server(
    store: ConfigStore, admin: Conn
) -> None:
    await stored(admin, {"duration_minutes": "a long time"})
    with pytest.raises(ConfigError, match=r"giveaways.*42"):
        await store.load(GUILD, "giveaways", GiveawayConfig)


async def test_config_is_per_server(store: ConfigStore) -> None:
    await store.save(GUILD, "giveaways", GiveawayConfig(duration_minutes=1), 7)
    assert await store.load(GUILD + 1, "giveaways", GiveawayConfig) == GiveawayConfig()

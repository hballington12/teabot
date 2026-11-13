"""Per-server plugin config (D8, D10).

Stored config is validated through the plugin's current model where it enters, so defaults, aliases and
ignored fields carry it across versions. Config that the model refuses is an error naming the plugin and the
server, never a silent reset.
"""

import json

from pydantic import BaseModel, ValidationError

from teapot.db.pool import Database

LOAD = "SELECT config FROM core.guild_plugins WHERE guild_id = $1 AND plugin_id = $2"
SAVE = """
INSERT INTO core.guild_plugins (guild_id, plugin_id, config, updated_by) VALUES ($1, $2, $3::jsonb, $4)
ON CONFLICT (guild_id, plugin_id) DO UPDATE
SET config = EXCLUDED.config, updated_by = EXCLUDED.updated_by, updated_at = now()
"""


class ConfigError(ValueError):
    """A server's stored config no longer validates against the plugin's model."""


class ConfigStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def load[C: BaseModel](self, guild_id: int, plugin_id: str, model: type[C]) -> C:
        raw: str | None = await self.db.fetchval(LOAD, guild_id, plugin_id)
        try:
            return model.model_validate(json.loads(raw) if raw is not None else {})
        except ValidationError as exc:
            raise ConfigError(
                f"stored config of {plugin_id} in server {guild_id} does not validate: {exc}"
            ) from exc

    async def save(self, guild_id: int, plugin_id: str, config: BaseModel, updated_by: int) -> None:
        await self.db.execute(SAVE, guild_id, plugin_id, config.model_dump_json(), updated_by)

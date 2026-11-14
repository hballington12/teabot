-- The command set Discord last accepted for each server, as a hash (D32). A sync job compares the set it
-- would send with this hash and sends nothing when they match, so startup costs nothing for unchanged
-- servers. Discord ids are never 0, so guild_id 0 holds the global set: the admin plugin's commands.

CREATE TABLE core.command_sync (
    guild_id bigint PRIMARY KEY,
    hash text NOT NULL,
    synced_at timestamptz NOT NULL DEFAULT now()
);

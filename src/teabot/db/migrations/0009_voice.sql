-- Voice sessions (D54): the voice channel the bot is in for each server, and the plugin that joined it. A bot has one
-- voice connection per server, so the server is the key. The row outlives a restart, so the process that starts
-- next asks the plugin to resume; the plugin's own tables hold what was playing.
CREATE TABLE core.voice_sessions (
    guild_id bigint PRIMARY KEY,
    plugin_id text NOT NULL,
    channel_id bigint NOT NULL,
    joined_at timestamptz NOT NULL DEFAULT now()
);

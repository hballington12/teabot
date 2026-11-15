-- The outbox: posts a plugin queues inside a transaction, so they commit with its writes. Each row holds the post as
-- it should show now. A send or an edit raises its version and queues a core post_message job, which brings the
-- Discord message up to that version; shown_version is the version Discord shows.
CREATE TABLE core.posts (
    id bigserial PRIMARY KEY,
    guild_id bigint NOT NULL,
    plugin_id text NOT NULL,
    channel_id bigint NOT NULL,
    message jsonb NOT NULL,
    version integer NOT NULL DEFAULT 1,
    shown_version integer NOT NULL DEFAULT 0,
    message_id bigint,
    deleted boolean NOT NULL DEFAULT false,
    error text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX posts_guild_plugin ON core.posts (guild_id, plugin_id);

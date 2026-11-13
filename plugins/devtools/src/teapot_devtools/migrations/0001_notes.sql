CREATE TABLE notes (
    guild_id bigint NOT NULL,
    text text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

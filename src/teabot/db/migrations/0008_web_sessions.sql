-- The dashboard's sign-ins. The cookie holds a random token, and only its hash is kept here, as for MCP tokens
-- (D16). guild_ids are the servers Discord said the member manages when they signed in.
CREATE TABLE core.web_sessions (
    token_hash bytea PRIMARY KEY,
    user_id bigint NOT NULL,
    name text NOT NULL,
    guild_ids bigint[] NOT NULL,
    csrf text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);
CREATE INDEX web_sessions_expires ON core.web_sessions (expires_at);
CREATE INDEX web_sessions_user ON core.web_sessions (user_id);

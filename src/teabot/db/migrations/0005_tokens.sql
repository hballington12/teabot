-- Bearer tokens (D16, D17, D20). A token is `teabot_<id>_<secret>`; only the SHA-256 of the secret is kept.
-- Each acts as the member who made it, in one server, up to a maximum risk and, when allowed_actions is not
-- empty, only for those actions. Rotating is revoking and creating.

CREATE TABLE core.tokens (
    id text PRIMARY KEY,
    secret_hash bytea NOT NULL,
    guild_id bigint NOT NULL,
    user_id bigint NOT NULL,
    label text NOT NULL,
    max_risk integer NOT NULL CHECK (max_risk BETWEEN 1 AND 3),
    allowed_actions text[] NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    last_used timestamptz,
    revoked_at timestamptz
);
CREATE INDEX tokens_guild_user ON core.tokens (guild_id, user_id);

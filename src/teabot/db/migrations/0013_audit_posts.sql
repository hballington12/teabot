-- The log channel's latest post in each server (D24). Entries by one member for one action, close together, are
-- gathered into it as lines; `audit_ids` lists them, so a repeated post job finds its line already there.
CREATE TABLE core.audit_posts (
    guild_id bigint PRIMARY KEY,
    channel_id bigint NOT NULL,
    message_id bigint NOT NULL,
    audit_ids bigint[] NOT NULL,
    lines text[] NOT NULL,
    posted_at timestamptz NOT NULL
);

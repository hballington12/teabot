-- Role changes to many members (role-changes.md): one row per change, and one per member it changes. A change runs
-- as the plugin's job, a short burst at a time; its grant is the apply's audit row, which names who confirmed it.
CREATE TABLE role_changes (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    guild_id bigint NOT NULL,
    role_id bigint NOT NULL,
    give boolean NOT NULL,
    -- The filter it was planned with, checked again for each member; null for a revert, which names its members.
    filter jsonb,
    grant_id bigint NOT NULL,
    state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'running', 'stopping', 'done', 'stopped')),
    why text,
    reverts bigint,
    next_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    progress_at timestamptz,
    finished_at timestamptz,
    UNIQUE (guild_id, id)
);
CREATE INDEX role_changes_open ON role_changes (guild_id, id) WHERE state IN ('queued', 'running', 'stopping');

CREATE TABLE role_change_members (
    guild_id bigint NOT NULL,
    change_id bigint NOT NULL,
    user_id teabot.member_id NOT NULL,
    outcome text NOT NULL DEFAULT 'pending' CHECK (outcome IN ('pending', 'changed', 'gone', 'skipped')),
    PRIMARY KEY (guild_id, change_id, user_id),
    FOREIGN KEY (guild_id, change_id) REFERENCES role_changes (guild_id, id) ON DELETE CASCADE
);

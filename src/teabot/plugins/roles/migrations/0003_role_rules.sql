-- Role rules (clan-links.md, part 2): within a scope, each member holds the role of the first step whose label they
-- have, and none of the rule's other roles. A rule stores its end state, never its changes; its grant is the apply's
-- audit row, which names who confirmed it.
CREATE TABLE rules (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    guild_id bigint NOT NULL,
    -- The members it acts on, as a filter, whose labels_from also names the plugin whose labels the steps are.
    scope jsonb NOT NULL,
    -- Its steps, highest first: roles[i] for a member with labels[i].
    roles bigint[] NOT NULL,
    labels text[] NOT NULL,
    cap int,
    grant_id bigint NOT NULL,
    state text NOT NULL DEFAULT 'on' CHECK (state IN ('on', 'stopped')),
    why text,
    -- A run its plan showed, confirmed, so it goes through above the cap; cleared when the run ends.
    approved int,
    -- A run above the cap was posted once, so it is not posted again until the rule runs.
    held boolean NOT NULL DEFAULT false,
    -- A run under way, and the members it has changed so far, so the directory's lag never changes one twice.
    running boolean NOT NULL DEFAULT false,
    handled bigint[] NOT NULL DEFAULT '{}',
    changed_today int NOT NULL DEFAULT 0,
    last_run_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (guild_id, id)
);

-- One pace per server: a pending trigger's run, and a run in bursts, which matching changes wait behind.
CREATE TABLE rule_pace (
    guild_id bigint PRIMARY KEY,
    due_at timestamptz,
    busy_until timestamptz
);

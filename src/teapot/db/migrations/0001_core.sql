-- The core tables of milestone 1 (D9, D31, D40, D49). core.migrations is created by the runner itself.

CREATE TABLE core.guilds (
    guild_id bigint PRIMARY KEY,
    joined_at timestamptz NOT NULL DEFAULT now(),
    removed_at timestamptz,
    purge_job_id bigint
);

CREATE TABLE core.guild_plugins (
    guild_id bigint NOT NULL,
    plugin_id text NOT NULL,
    enabled boolean NOT NULL DEFAULT false,
    config jsonb NOT NULL DEFAULT '{}',
    updated_by bigint,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, plugin_id)
);

CREATE TABLE core.jobs (
    id bigserial PRIMARY KEY,
    guild_id bigint,
    plugin_id text NOT NULL,
    handler text NOT NULL,
    run_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL DEFAULT '{}',
    state text NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending', 'running', 'done', 'failed', 'cancelled')),
    lease_until timestamptz,
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 5,
    last_error text,
    progress jsonb,
    started_by bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);

-- Claims scan only pending jobs, however many finished rows pile up (D31).
CREATE INDEX jobs_pending_run_at ON core.jobs (run_at) WHERE state = 'pending';
-- At most one running plan apply per server (D21, D31).
CREATE UNIQUE INDEX jobs_one_apply_per_guild ON core.jobs (guild_id) WHERE handler = 'apply' AND state = 'running';
CREATE INDEX jobs_guild ON core.jobs (guild_id);

CREATE TABLE core.processes (
    process_id text PRIMARY KEY,
    host text NOT NULL,
    shard_ids integer[] NOT NULL,
    shard_count integer NOT NULL,
    version text NOT NULL,
    plugins jsonb NOT NULL DEFAULT '{}',
    started_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

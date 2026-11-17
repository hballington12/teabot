-- The member directory (D55): every server's members, their history, and the state of each server's copy.

-- One row per member per server. A member who leaves keeps their row, with left_at set, until retention deletes it.
-- observed_at is when the bot received what the row says, so a reconcile's page never undoes a newer event.
CREATE TABLE core.members (
    guild_id bigint NOT NULL,
    user_id teabot.member_id NOT NULL,
    name text NOT NULL,
    global_name text,
    nickname text,
    bot boolean NOT NULL DEFAULT false,
    role_ids bigint[] NOT NULL DEFAULT '{}',
    joined_at timestamptz,
    premium_since timestamptz,
    timed_out_until timestamptz,
    pending boolean NOT NULL DEFAULT false,
    flags integer NOT NULL DEFAULT 0,
    -- The latest join's method, from Discord's member search: its raw join_source_type, kept as a number so a
    -- value Discord adds is never lost.
    join_source integer,
    source_invite_code text,
    inviter_id bigint,
    left_at timestamptz,
    observed_at timestamptz NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX members_guild_left ON core.members (guild_id, left_at);
CREATE INDEX members_guild_joined ON core.members (guild_id, joined_at);
CREATE INDEX members_user ON core.members (user_id);

-- The history, partitioned by month so retention drops a month whole. A server-level row, such as a deleted role,
-- has no user_id. detail holds what the kind needs: a join's method, roles added and removed, a nickname's old and
-- new values, a timeout's end, or a deleted role's name and holders.
CREATE TABLE core.member_events (
    guild_id bigint NOT NULL,
    user_id teabot.member_id,
    kind text NOT NULL CHECK (kind IN (
        'joined', 'left', 'kicked', 'banned', 'unbanned', 'timeout', 'roles', 'nickname', 'role_deleted'
    )),
    at timestamptz NOT NULL,
    -- For a change a reconcile found: it happened between since and at.
    since timestamptz,
    source text NOT NULL CHECK (source IN ('event', 'reconcile')),
    actor_id bigint,
    reason text,
    detail jsonb NOT NULL DEFAULT '{}'
) PARTITION BY RANGE (at);
CREATE TABLE core.member_events_default PARTITION OF core.member_events DEFAULT;
CREATE INDEX member_events_guild_at ON core.member_events (guild_id, at);
CREATE INDEX member_events_guild_user_at ON core.member_events (guild_id, user_id, at);
CREATE INDEX member_events_user ON core.member_events (user_id);

CREATE TABLE core.directory_state (
    guild_id bigint PRIMARY KEY,
    -- When history starts: the end of the server's first reconcile, its backfill.
    history_from timestamptz,
    backfilled boolean NOT NULL DEFAULT false,
    reconciled_at timestamptz,
    -- Events for the server were dropped since its last reconcile, so the directory may be behind until the next.
    dropped boolean NOT NULL DEFAULT false,
    -- The last reconcile stopped short: Discord listed far fewer members than it counts.
    guard_stopped boolean NOT NULL DEFAULT false,
    -- Off above the operator's member-count ceiling.
    off boolean NOT NULL DEFAULT false,
    -- The newest join the join-method lookup has read.
    joins_read_to timestamptz
);

-- Partition upkeep needs the parent's owner, as for the audit log's look-ups (0002).
CREATE FUNCTION core.ensure_member_event_partitions(p_from date, p_months integer) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_temp AS $$
DECLARE
    m date;
    name text;
BEGIN
    FOR i IN 0..p_months LOOP
        m := (date_trunc('month', p_from) + make_interval(months => i))::date;
        name := 'member_events_p' || to_char(m, 'YYYYMM');
        IF to_regclass('core.' || name) IS NULL THEN
            BEGIN
                EXECUTE format(
                    'CREATE TABLE core.%I PARTITION OF core.member_events FOR VALUES FROM (%L) TO (%L)',
                    name, m::timestamp AT TIME ZONE 'UTC', (m + interval '1 month')::timestamp AT TIME ZONE 'UTC'
                );
            EXCEPTION WHEN check_violation THEN
                -- The default partition already holds rows for that month; they age out there instead.
                NULL;
            END;
        END IF;
    END LOOP;
END $$;

-- Drops the months that end before p_before.
CREATE FUNCTION core.drop_member_event_partitions(p_before date) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_temp AS $$
DECLARE
    child text;
    dropped integer := 0;
BEGIN
    FOR child IN
        SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
        WHERE i.inhparent = 'core.member_events'::regclass AND c.relname ~ '^member_events_p[0-9]{6}$'
    LOOP
        IF (to_date(substr(child, 16), 'YYYYMM') + interval '1 month')::date <= p_before THEN
            EXECUTE format('DROP TABLE core.%I', child);
            dropped := dropped + 1;
        END IF;
    END LOOP;
    RETURN dropped;
END $$;

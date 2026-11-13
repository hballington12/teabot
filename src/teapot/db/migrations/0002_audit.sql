-- The audit log (D24). Changes and refusals go to core.audit_log; lookups to core.audit_reads, partitioned
-- by day so retention drops whole partitions. The default partition catches any day without its own, so an
-- insert never fails for want of a partition.

CREATE TABLE core.audit_log (
    id bigserial PRIMARY KEY,
    time timestamptz NOT NULL DEFAULT now(),
    guild_id bigint NOT NULL,
    user_id bigint NOT NULL,
    token_id text,
    surface text NOT NULL,
    action text NOT NULL,
    input jsonb NOT NULL,
    risk integer NOT NULL,
    outcome text NOT NULL CHECK (outcome IN ('started', 'planned', 'ok', 'refused', 'error')),
    error text,
    diff_hash text,
    confirm text UNIQUE,
    plan_id bigint REFERENCES core.audit_log (id),
    job_id bigint
);
CREATE INDEX audit_log_time ON core.audit_log (time);
CREATE INDEX audit_log_guild_time ON core.audit_log (guild_id, time DESC);

CREATE TABLE core.audit_reads (
    time timestamptz NOT NULL DEFAULT now(),
    guild_id bigint NOT NULL,
    user_id bigint NOT NULL,
    token_id text,
    surface text NOT NULL,
    action text NOT NULL,
    input jsonb NOT NULL,
    outcome text NOT NULL,
    error text
) PARTITION BY RANGE (time);
CREATE TABLE core.audit_reads_default PARTITION OF core.audit_reads DEFAULT;

-- Partition upkeep needs the parent's owner. These run as the owner, so the app role stays unprivileged;
-- plugin roles cannot reach them, having no rights on the core schema.
CREATE FUNCTION core.ensure_audit_read_partitions(p_from date, p_days integer) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_temp AS $$
DECLARE
    d date;
    name text;
BEGIN
    FOR i IN 0..p_days LOOP
        d := p_from + i;
        name := 'audit_reads_p' || to_char(d, 'YYYYMMDD');
        IF to_regclass('core.' || name) IS NULL THEN
            BEGIN
                EXECUTE format(
                    'CREATE TABLE core.%I PARTITION OF core.audit_reads FOR VALUES FROM (%L) TO (%L)',
                    name, d::timestamp AT TIME ZONE 'UTC', (d + 1)::timestamp AT TIME ZONE 'UTC'
                );
            EXCEPTION WHEN check_violation THEN
                -- The default partition already holds rows for that day; they age out there instead.
                NULL;
            END;
        END IF;
    END LOOP;
END $$;

CREATE FUNCTION core.drop_audit_read_partitions(p_before date) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_temp AS $$
DECLARE
    child text;
    dropped integer := 0;
BEGIN
    FOR child IN
        SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
        WHERE i.inhparent = 'core.audit_reads'::regclass AND c.relname ~ '^audit_reads_p[0-9]{8}$'
    LOOP
        IF to_date(substr(child, 14), 'YYYYMMDD') < p_before THEN
            EXECUTE format('DROP TABLE core.%I', child);
            dropped := dropped + 1;
        END IF;
    END LOOP;
    RETURN dropped;
END $$;

-- Plugin events (events-and-tickets.md): what a plugin announced, kept 30 days for its subscribers and the feed.
-- A row is written in the emitting plugin's transaction, through its own emit_event, so it exists exactly when the
-- change that caused it commits.
--
-- CACHE 1 (the default, pinned): an emitter locks the thing an event is about before it emits, so for one thing a
-- later lock holder always draws a higher ID.
CREATE SEQUENCE core.events_id_seq CACHE 1;

CREATE TABLE core.events (
    id bigint PRIMARY KEY DEFAULT nextval('core.events_id_seq'),
    -- The writing transaction, so the feed returns a row only once nothing before it can still commit.
    tx_id xid8 NOT NULL DEFAULT pg_current_xact_id(),
    guild_id bigint NOT NULL,
    source text NOT NULL,
    name text NOT NULL,
    payload jsonb NOT NULL,
    -- The member who caused it, from the transaction's started_by; 0 once their data is deleted.
    by bigint,
    -- The payload's member fields, so deleting a member's data deletes the events that name them.
    member_ids teabot.member_id[] NOT NULL DEFAULT '{}',
    -- The paths of the payload's UntrustedText fields, so the feed marks them after the emitter is gone.
    untrusted text[] NOT NULL DEFAULT '{}',
    at timestamptz NOT NULL DEFAULT now()
);
ALTER SEQUENCE core.events_id_seq OWNED BY core.events.id;

CREATE INDEX events_feed ON core.events (guild_id, tx_id, id);
CREATE INDEX events_tx ON core.events (tx_id, guild_id);
CREATE INDEX events_members ON core.events USING gin (member_ids);
CREATE INDEX events_at ON core.events (at);

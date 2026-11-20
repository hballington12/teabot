-- Tickets (events-and-tickets.md, part 3): queues of items members claim, and the claims handlers settle.
CREATE TABLE queues (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    guild_id bigint NOT NULL,
    name text NOT NULL,
    channel_id bigint NOT NULL,
    -- Roles that may claim; everyone when empty. Roles that handle; Manage Server always may.
    claimers bigint[] NOT NULL DEFAULT '{}',
    handlers bigint[] NOT NULL DEFAULT '{}',
    per_day int NOT NULL DEFAULT 10,
    handlers_channel_id bigint,
    -- The board's post in the outbox, once posted.
    board_post bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (guild_id, id)
);

CREATE TABLE tickets (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    guild_id bigint NOT NULL,
    queue_id bigint NOT NULL,
    title text NOT NULL,
    body text NOT NULL DEFAULT '',
    -- The creator's own reference, such as a game account's ID: one per queue, in every state.
    key text,
    state text NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'closed')),
    resolution text CHECK (resolution IN ('accepted', 'cancelled')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    closed_at timestamptz,
    UNIQUE (guild_id, id),
    FOREIGN KEY (guild_id, queue_id) REFERENCES queues (guild_id, id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX tickets_key ON tickets (guild_id, queue_id, key) WHERE key IS NOT NULL;
CREATE INDEX tickets_open ON tickets (guild_id, queue_id) WHERE state = 'open';
CREATE INDEX tickets_changed ON tickets (guild_id, queue_id, updated_at);

CREATE TABLE claims (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    guild_id bigint NOT NULL,
    ticket_id bigint NOT NULL,
    member teabot.member_id NOT NULL,
    note text NOT NULL DEFAULT '',
    state text NOT NULL DEFAULT 'waiting'
        CHECK (state IN ('waiting', 'accepted', 'rejected', 'withdrawn', 'revoked')),
    settled_by teabot.member_actor,
    settled_at timestamptz,
    reason text,
    -- Its post in the handlers' channel, if the queue has one.
    handler_post bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (guild_id, id),
    FOREIGN KEY (guild_id, ticket_id) REFERENCES tickets (guild_id, id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX claims_one_waiting ON claims (guild_id, ticket_id, member) WHERE state = 'waiting';
CREATE INDEX claims_ticket ON claims (guild_id, ticket_id);
CREATE INDEX claims_member ON claims (guild_id, member, created_at);

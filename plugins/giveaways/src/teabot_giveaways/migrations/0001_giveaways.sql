CREATE TABLE giveaways (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    guild_id bigint NOT NULL,
    channel_id bigint NOT NULL,
    prize text NOT NULL,
    winners int NOT NULL,
    ends_at timestamptz NOT NULL,
    state text NOT NULL DEFAULT 'running' CHECK (state IN ('running', 'drawn', 'cancelled')),
    UNIQUE (guild_id, id)
);

CREATE TABLE entries (
    guild_id bigint NOT NULL,
    giveaway_id bigint NOT NULL,
    member_id bigint NOT NULL,
    won boolean NOT NULL DEFAULT false,
    PRIMARY KEY (guild_id, giveaway_id, member_id),
    FOREIGN KEY (guild_id, giveaway_id) REFERENCES giveaways (guild_id, id)
);

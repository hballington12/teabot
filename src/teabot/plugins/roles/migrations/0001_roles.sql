CREATE TABLE posts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    guild_id bigint NOT NULL,
    channel_id bigint NOT NULL,
    message_id bigint,
    title text NOT NULL,
    note text NOT NULL DEFAULT '',
    UNIQUE (guild_id, id)
);

CREATE TABLE offers (
    guild_id bigint NOT NULL,
    post_id bigint NOT NULL,
    role_id bigint NOT NULL,
    place int NOT NULL,
    PRIMARY KEY (guild_id, post_id, role_id),
    FOREIGN KEY (guild_id, post_id) REFERENCES posts (guild_id, id) ON DELETE CASCADE
);

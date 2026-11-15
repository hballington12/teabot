CREATE TABLE entries (
    guild_id bigint NOT NULL,
    member_id teabot.member_id NOT NULL,
    PRIMARY KEY (guild_id, member_id)
);

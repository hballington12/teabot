-- Member labels: short strings a plugin keeps about a server's members, which filters match while
-- they are fresh. A member's row holds that plugin's labels for them; a server's state row says how fresh the
-- plugin's data is.
CREATE TABLE core.member_labels (
    guild_id bigint NOT NULL,
    plugin_id text NOT NULL,
    user_id teabot.member_id NOT NULL,
    labels text[] NOT NULL,
    PRIMARY KEY (guild_id, plugin_id, user_id)
);
CREATE INDEX member_labels_user ON core.member_labels (user_id);

CREATE TABLE core.label_state (
    guild_id bigint NOT NULL,
    plugin_id text NOT NULL,
    -- How fresh the data behind the labels is, as the plugin says, such as its last successful fetch.
    as_of timestamptz NOT NULL,
    written_at timestamptz NOT NULL,
    PRIMARY KEY (guild_id, plugin_id)
);

-- A draft can come from a button that asks for text in a form, so the submit runs through the door it came from.
ALTER TABLE core.interaction_drafts ADD COLUMN via text NOT NULL DEFAULT 'slash';

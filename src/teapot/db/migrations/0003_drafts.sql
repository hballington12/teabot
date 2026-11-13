-- Slash command options waiting for their modal (D29, D32, D40). A modal's custom id holds only the draft id,
-- so any process can finish the submit and nothing lives in process memory. Drafts expire after minutes.

CREATE TABLE core.interaction_drafts (
    id uuid PRIMARY KEY,
    guild_id bigint NOT NULL,
    user_id bigint NOT NULL,
    action text NOT NULL,
    input jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX interaction_drafts_created ON core.interaction_drafts (created_at);

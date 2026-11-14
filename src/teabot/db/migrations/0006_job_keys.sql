-- Job keys (D31): a plugin's job can carry a key, so scheduling the same key again moves the pending job instead of
-- adding another, and the key can cancel it. Only pending jobs are unique by key: a running job with the key is left
-- alone, and scheduling it again queues a new pending one.
ALTER TABLE core.jobs ADD COLUMN key text;
CREATE UNIQUE INDEX jobs_pending_key ON core.jobs (plugin_id, guild_id, key) WHERE state = 'pending' AND key IS NOT NULL;

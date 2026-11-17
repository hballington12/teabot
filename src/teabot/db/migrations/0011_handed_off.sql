-- Work that outlasts its apply (role-changes.md, D24): an apply that hands work off ends "handed_off", and the work's
-- outcome follows as its own row, which `follows` links to the apply's.
ALTER TABLE core.audit_log DROP CONSTRAINT audit_log_outcome_check;
ALTER TABLE core.audit_log ADD CONSTRAINT audit_log_outcome_check
    CHECK (outcome IN ('started', 'planned', 'ok', 'refused', 'error', 'handed_off'));
ALTER TABLE core.audit_log ADD COLUMN follows bigint REFERENCES core.audit_log (id) ON DELETE SET NULL;
CREATE UNIQUE INDEX audit_log_one_outcome ON core.audit_log (follows) WHERE follows IS NOT NULL;

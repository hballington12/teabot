-- Entrants' IDs as members' IDs, so deleting a member's data finds them (D11).
ALTER TABLE entries ALTER COLUMN member_id TYPE teabot.member_id;

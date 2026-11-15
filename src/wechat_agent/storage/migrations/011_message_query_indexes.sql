-- Match timezone-aware predicates; keep source text and revisions untouched.
CREATE INDEX messages_visible_author_time
ON messages(account_id,sender_id,julianday(sent_at),message_id,conversation_id)
WHERE kind NOT IN ('system','revoke');
CREATE INDEX messages_visible_room_time
ON messages(account_id,conversation_id,julianday(sent_at),message_id)
WHERE kind NOT IN ('system','revoke');
CREATE INDEX attachments_message ON attachments(account_id,message_id,attachment_id);
-- A single-column index also carries rowid order within each account.
CREATE INDEX message_revisions_account ON message_revisions(account_id);

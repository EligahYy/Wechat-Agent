ALTER TABLE contacts ADD COLUMN identity_state TEXT NOT NULL DEFAULT 'active' CHECK(identity_state IN ('active','quarantined'));
ALTER TABLE contacts ADD COLUMN identity_reason TEXT;
UPDATE contacts SET identity_state='quarantined',identity_reason='source_identity_invalid'
WHERE NOT wechat_person_id_valid(contact_id);
CREATE INDEX contacts_identity_role ON contacts(account_id,identity_state,role);

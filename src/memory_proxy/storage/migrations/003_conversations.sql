-- 003_conversations.sql — full-write conversation logs + daily audit support.
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_conversations_user_archived
    ON conversations(session_id, archived, created_at);

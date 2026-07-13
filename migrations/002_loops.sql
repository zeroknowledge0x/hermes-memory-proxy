-- 002_loops.sql — consolidate/reflect support (D-023).
-- Adds importance scoring + an append-only event log for audit/recovery.

ALTER TABLE memories
    ADD COLUMN IF NOT EXISTS importance REAL NOT NULL DEFAULT 0.5,
    ADD COLUMN IF NOT EXISTS tier TEXT NOT NULL DEFAULT 'semantic',
    ADD COLUMN IF NOT EXISTS consolidated BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    kind TEXT NOT NULL,            -- 'consolidate' | 'reflect' | 'extract' | 'inject'
    detail JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_events_user_kind
    ON events(user_id, kind, created_at DESC);

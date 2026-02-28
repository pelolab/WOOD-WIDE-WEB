-- NOTE: CREATE INDEX CONCURRENTLY must run outside explicit transaction blocks.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ledger_analytics_lookup
ON ledger (circle_id, circle_month DESC, timestamp DESC);

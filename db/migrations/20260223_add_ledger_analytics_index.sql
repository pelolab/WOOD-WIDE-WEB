-- migration: add_ledger_analytics_index.sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ledger_analytics_lookup
ON ledger (circle_id, circle_month DESC, timestamp DESC);

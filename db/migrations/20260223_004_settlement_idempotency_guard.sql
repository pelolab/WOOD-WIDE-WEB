-- Prevent exact duplicate settlements when idempotency-key flow is bypassed.
-- Blocker mitigation for financial double-processing.
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_settlement_dedup
ON ledger (circle_id, debt_id, user_id, amount)
WHERE tx_type = 'SETTLEMENT';

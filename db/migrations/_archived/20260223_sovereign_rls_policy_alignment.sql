-- ===========================================================================
-- SUSUCIRCLE RLS POLICIES (SOVEREIGN ARCHITECTURE)
-- Follow-up alignment migration for canonical policy names/expressions.
-- ===========================================================================

BEGIN;

-- Ensure RLS is enabled on relevant tables.
ALTER TABLE circles ENABLE ROW LEVEL SECURITY;
ALTER TABLE circle_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- Remove previous policy variants so canonical policies are authoritative.
DROP POLICY IF EXISTS "Members can view their own circles" ON circles;
DROP POLICY IF EXISTS "circle_access_policy" ON circles;

DROP POLICY IF EXISTS "Members can view relevant ledger entries" ON ledger;
DROP POLICY IF EXISTS "Strict Backend-Only Writes" ON ledger;
DROP POLICY IF EXISTS "ledger_read_policy" ON ledger;
DROP POLICY IF EXISTS "ledger_write_protection" ON ledger;

DROP POLICY IF EXISTS "Users can view their own profile" ON users;
DROP POLICY IF EXISTS "user_privacy_policy" ON users;

-- 1. CIRCLES TABLE: Only members can see the group details.
CREATE POLICY "circle_access_policy" ON circles
FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM circle_members
    WHERE circle_id = circles.id AND user_id = auth.uid()
  )
);

-- 2. LEDGER TABLE: Financial Transparency vs. Privacy
CREATE POLICY "ledger_read_policy" ON ledger
FOR SELECT
USING (
  user_id = auth.uid() OR
  related_user_id = auth.uid() OR
  EXISTS (
    SELECT 1 FROM circle_members
    WHERE circle_id = ledger.circle_id
    AND user_id = auth.uid()
    AND status = 'ACTIVE'
  )
);

-- 3. LEDGER WRITE PROTECTION: Backend service role only.
CREATE POLICY "ledger_write_protection" ON ledger
FOR INSERT
WITH CHECK (auth.role() = 'service_role');

-- 4. USERS TABLE: Privacy lock.
CREATE POLICY "user_privacy_policy" ON users
FOR SELECT
USING (id = auth.uid());

COMMIT;

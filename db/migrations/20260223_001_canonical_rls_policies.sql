BEGIN;

ALTER TABLE circles ENABLE ROW LEVEL SECURITY;
ALTER TABLE circle_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE social_vouchers ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Members can view their own circles" ON circles;
DROP POLICY IF EXISTS "circle_access_policy" ON circles;
CREATE POLICY circle_access_policy ON circles
FOR SELECT USING (
  EXISTS (SELECT 1 FROM circle_members WHERE circle_id = circles.id AND user_id = auth.uid())
);

DROP POLICY IF EXISTS "Members can view relevant ledger entries" ON ledger;
DROP POLICY IF EXISTS "ledger_read_policy" ON ledger;
CREATE POLICY ledger_read_policy ON ledger
FOR SELECT USING (
  user_id = auth.uid()
  OR related_user_id = auth.uid()
  OR EXISTS (
    SELECT 1 FROM circle_members
    WHERE circle_id = ledger.circle_id AND user_id = auth.uid() AND status = 'ACTIVE'
  )
);

DROP POLICY IF EXISTS "Strict Backend-Only Writes" ON ledger;
DROP POLICY IF EXISTS "ledger_write_protection" ON ledger;
CREATE POLICY ledger_write_protection ON ledger
FOR INSERT WITH CHECK (auth.role() = 'service_role');

DROP POLICY IF EXISTS "Users can view their own profile" ON users;
DROP POLICY IF EXISTS "user_privacy_policy" ON users;
CREATE POLICY user_privacy_policy ON users
FOR SELECT USING (id = auth.uid());

DROP POLICY IF EXISTS social_vouchers_view ON social_vouchers;
CREATE POLICY social_vouchers_view ON social_vouchers
FOR SELECT USING (auth.uid() = prospect_id OR auth.uid() = voucher_id);

DROP POLICY IF EXISTS social_vouchers_insert ON social_vouchers;
CREATE POLICY social_vouchers_insert ON social_vouchers
FOR INSERT WITH CHECK (auth.uid() = voucher_id);

COMMIT;

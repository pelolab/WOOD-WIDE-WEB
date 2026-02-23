-- Enable Row Level Security and baseline access policies
-- for core SusuCircle production tables.

BEGIN;

-- 1. Enable RLS on the core tables
ALTER TABLE circles ENABLE ROW LEVEL SECURITY;
ALTER TABLE circle_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- 2. Policy: Users can only view their own global profiles
DROP POLICY IF EXISTS "Users can view their own profile" ON users;
CREATE POLICY "Users can view their own profile"
ON users
FOR SELECT
USING (auth.uid() = id);

-- 3. Policy: Users can only see circles they are a part of
DROP POLICY IF EXISTS "Members can view their own circles" ON circles;
CREATE POLICY "Members can view their own circles"
ON circles
FOR SELECT
USING (
    id IN (
        SELECT circle_id
        FROM circle_members
        WHERE user_id = auth.uid()
    )
);

-- 4. Policy: Ledger Transparency Rule (read-only)
DROP POLICY IF EXISTS "Members can view relevant ledger entries" ON ledger;
CREATE POLICY "Members can view relevant ledger entries"
ON ledger
FOR SELECT
USING (
    user_id = auth.uid()
    OR related_user_id = auth.uid()
    OR circle_id IN (
        SELECT circle_id
        FROM circle_members
        WHERE user_id = auth.uid() AND status = 'ACTIVE'
    )
);

-- 5. Policy: Backend service-role-only writes to ledger
DROP POLICY IF EXISTS "Strict Backend-Only Writes" ON ledger;
CREATE POLICY "Strict Backend-Only Writes"
ON ledger
FOR INSERT
WITH CHECK (
    current_setting('request.jwt.claims', true)::json->>'role' = 'service_role'
);

COMMIT;

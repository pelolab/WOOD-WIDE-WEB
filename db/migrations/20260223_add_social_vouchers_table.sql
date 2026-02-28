-- Create social_vouchers table for Tier-1 Social Proof onboarding.

BEGIN;

CREATE TABLE IF NOT EXISTS social_vouchers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prospect_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    voucher_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    -- Ensure a member can only vouch for a specific prospect once
    UNIQUE (prospect_id, voucher_id)
);

-- RLS: Prospects can see who vouched for them; vouchers can see who they vouched for.
ALTER TABLE social_vouchers ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS social_vouchers_view ON social_vouchers;
CREATE POLICY social_vouchers_view ON social_vouchers
FOR SELECT
USING (auth.uid() = prospect_id OR auth.uid() = voucher_id);

-- Only active members can vouch. This check happens in the application layer.

COMMIT;

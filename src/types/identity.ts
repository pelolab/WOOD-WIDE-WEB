export type VerificationTierStatus = 'unverified' | 'pending' | 'verified' | 'failed' | 'none';

export interface VerificationStatusResponse {
  user_id: string;
  tier1_status: VerificationTierStatus;
  tier2_status: VerificationTierStatus;
  tier3_status: VerificationTierStatus;
}

export interface SubmitVerificationPayload {
  tier: 1 | 2 | 3;
  provider_ref?: string;
  document_hash?: string;
}

export interface ProspectInfoResponse {
  full_name: string;
  tier1_status: VerificationTierStatus;
}

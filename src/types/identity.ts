export type VerificationTierStatus = 'unverified' | 'pending' | 'verified' | 'failed';

export interface VerificationStatusResponse {
  tier1_status: VerificationTierStatus;
  tier2_status: VerificationTierStatus;
  tier3_status: VerificationTierStatus;
}

export interface SubmitVerificationPayload {
  tier: 1 | 2 | 3;
  provider_ref: string;
}


export interface ProspectInfoResponse {
  full_name: string;
  tier1_status: VerificationTierStatus | 'none';
}

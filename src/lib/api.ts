import { MemberAnalyticsRow, SovereigntyProjection } from '../types/analytics';
import { ProspectInfoResponse, SubmitVerificationPayload, VerificationStatusResponse } from '../types/identity';
import { LedgerEntry } from '../types/ledger';

const parseAmount = (value: number | string): number =>
  typeof value === 'number' ? value : Number.parseFloat(value);

const getAuthHeaders = (): Record<string, string> => {
  const token = localStorage.getItem('jwt_token');
  if (!token) {
    throw new Error('Missing auth token');
  }
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  };
};

export const fetchLedger = async (circleId: string): Promise<LedgerEntry[]> => {
  const res = await fetch(`/api/cycles/${circleId}/ledger`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error('Failed to fetch ledger');
  return res.json();
};

export const settleArrears = async (
  circleId: string,
  memberId: string,
  amountPaid: string,
  debtId?: string,
): Promise<unknown> => {
  const res = await fetch(`/api/cycles/${circleId}/settle`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({ member_id: memberId, amount_paid: amountPaid, debt_id: debtId }),
  });
  if (!res.ok) throw new Error('Settlement transaction failed');
  return res.json();
};

export const fetchMemberAnalytics = async (
  circleId: string,
  memberId?: string,
): Promise<MemberAnalyticsRow[]> => {
  const params = new URLSearchParams();
  if (memberId) params.set('member_id', memberId);
  const res = await fetch(`/api/circles/${circleId}/analytics/members?${params.toString()}`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to fetch member analytics');
  return res.json();
};

export const fetchSovereigntyProjection = async (
  circleId: string,
  memberId: string,
): Promise<SovereigntyProjection> => {
  const params = new URLSearchParams({ member_id: memberId });
  const res = await fetch(`/api/circles/${circleId}/analytics/sovereignty?${params.toString()}`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to fetch sovereignty projection');
  const data = (await res.json()) as {
    group_liquidity: number | string;
    equivalent_loan_principal: number | string;
    equivalent_loan_interest: number | string;
    total_loan_repayment: number | string;
    savings_vs_loan: number | string;
  };
  return {
    groupLiquidity: parseAmount(data.group_liquidity),
    equivalentLoanPrincipal: parseAmount(data.equivalent_loan_principal),
    equivalentLoanInterest: parseAmount(data.equivalent_loan_interest),
    totalLoanRepayment: parseAmount(data.total_loan_repayment),
    savingsVsLoan: parseAmount(data.savings_vs_loan),
  };
};

export async function fetchVerificationStatus(): Promise<VerificationStatusResponse> {
  const res = await fetch('/api/identity/status', { headers: getAuthHeaders() });
  if (!res.ok) throw new Error('Failed to fetch verification status');
  return res.json();
}

export async function submitVerification(data: SubmitVerificationPayload): Promise<void> {
  const res = await fetch('/api/identity/verify', {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Verification request failed (${res.status}): ${text}`);
  }
}

export async function fetchProspectInfo(prospectId: string): Promise<ProspectInfoResponse> {
  const res = await fetch(`/api/identity/prospect/${prospectId}`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error('Failed to fetch prospect info');
  return res.json();
}

export async function fetchProspectDetails(prospectId: string): Promise<{ name: string; tier1_status: string }> {
  const res = await fetch(`/api/identity/prospect/${prospectId}`, { headers: getAuthHeaders() });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Failed to fetch prospect (${res.status}): ${text}`);
  }
  const data = (await res.json()) as ProspectInfoResponse;
  return { name: data.full_name, tier1_status: data.tier1_status };
}

export async function submitVouch(prospectId: string): Promise<void> {
  const res = await fetch(`/api/identity/vouch/${prospectId}`, { method: 'POST', headers: getAuthHeaders() });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Vouch failed (${res.status}): ${text}`);
  }
}

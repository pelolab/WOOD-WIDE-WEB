import { LedgerEntry } from '../types/ledger';
import { MemberAnalyticsRow } from '../types/analytics';
import { ProspectInfoResponse, VerificationStatusResponse } from '../types/identity';

// All API calls include JWT Bearer token for RLS compliance.
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
  const res = await fetch(`/api/cycles/${circleId}/ledger`, {
    headers: getAuthHeaders(),
  });

  if (!res.ok) {
    throw new Error('Failed to fetch ledger');
  }

  return res.json();
};

export const settleArrears = async (
  memberId: string,
  cashReceived: number,
  debtId?: string,
) => {
  const res = await fetch('/api/cycles/settle', {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({
      member_id: memberId,
      cash_received: cashReceived,
      debt_id: debtId,
    }),
  });

  if (!res.ok) {
    throw new Error('Settlement transaction failed');
  }

  return res.json();
};

export const fetchMemberAnalytics = async (
  circleId: string,
  memberId: string,
): Promise<MemberAnalyticsRow[]> => {
  const params = new URLSearchParams({
    circle_id: circleId,
    member_id: memberId,
  });

  const res = await fetch(`/api/member-analytics?${params.toString()}`, {
    headers: getAuthHeaders(),
  });

  if (!res.ok) {
    throw new Error('Failed to fetch member analytics');
  }

  return res.json();
};


export async function fetchVerificationStatus(): Promise<VerificationStatusResponse> {
  const res = await fetch('/api/identity/status');
  if (!res.ok) throw new Error('Failed to fetch verification status');
  return res.json();
}

export async function submitVerification(data: { tier: number; provider_ref?: string; document_hash?: string }): Promise<void> {
  const res = await fetch('/api/identity/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Verification request failed (${res.status}): ${text}`);
  }
}


export async function fetchProspectInfo(prospectId: string): Promise<ProspectInfoResponse> {
  const res = await fetch(`/api/identity/prospect/${prospectId}`, {
    headers: getAuthHeaders(),
  });

  if (!res.ok) {
    throw new Error('Failed to fetch prospect info');
  }

  return res.json();
}

export async function submitVouch(prospectId: string): Promise<void> {
  const res = await fetch(`/api/identity/vouch/${prospectId}`, { method: 'POST' });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Vouch failed (${res.status}): ${text}`);
  }
}


export async function fetchProspectDetails(prospectId: string): Promise<{ name: string; tier1_status: string }> {
  const res = await fetch(`/api/identity/prospect/${prospectId}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Failed to fetch prospect (${res.status}): ${text}`);
  }
  return res.json();
}

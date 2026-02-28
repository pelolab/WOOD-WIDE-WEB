export type PaymentStatus = 'verified' | 'failed' | 'pending';

export type TxType =
  | 'CONTRIBUTION'
  | 'PAYOUT'
  | 'ARREARS'
  | 'SETTLEMENT'
  | 'LATE_CONTRIBUTION'
  | 'DELAYED_PAYOUT'
  | 'LATE_FEE'
  | 'LATE_FEE_COMPENSATION'
  | 'REMOVAL_REFUND'
  | 'POT_HELD';

export interface LedgerEntry {
  id: string;
  circle_month: number;
  tx_type: TxType;
  member_id: string;
  amount: number | string;
  status: PaymentStatus;
  debt_id?: string;
  intended_for?: string;
  note: string;
  timestamp: string;
}

export interface MemberNetPosition {
  member_id: string;
  contributed: number;
  received: number;
  penalties: number;
  net: number;
  pending_arrears: number;
}

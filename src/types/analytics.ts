export interface MemberAnalyticsRow {
  entry_id: string;
  circle_id: string;
  member_id: string;
  circle_month: number;
  tx_type: string;
  amount: number | string;
  status: string;
  note: string;
  timestamp: string;
  scheduled_recipient_id: string | null;
}

export interface SovereigntyProjection {
  groupLiquidity: number;
  equivalentLoanPrincipal: number;
  equivalentLoanInterest: number;
  totalLoanRepayment: number;
  savingsVsLoan: number;
}

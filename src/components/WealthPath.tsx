import React, { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';

import { fetchMemberAnalytics } from '../lib/api';
import { MemberAnalyticsRow, SovereigntyProjection } from '../types/analytics';

interface WealthPathProps {
  circleId: string;
  userId: string;
}

const LOAN_PRINCIPAL = 3000;
const LOAN_APR = 0.18;
const LOAN_TERM_YEARS = 1;

const monthSorterDesc = (a: MemberAnalyticsRow, b: MemberAnalyticsRow): number => {
  if (b.circle_month !== a.circle_month) {
    return b.circle_month - a.circle_month;
  }

  return b.timestamp.localeCompare(a.timestamp);
};

const formatCurrency = (amount: number): string =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);

export const WealthPath: React.FC<WealthPathProps> = ({ circleId, userId }) => {
  const [analyticsRows, setAnalyticsRows] = useState<MemberAnalyticsRow[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;

    const loadMemberAnalytics = async (): Promise<void> => {
      setLoading(true);
      setError(null);

      try {
        const rows = await fetchMemberAnalytics(circleId, userId);
        if (alive) {
          setAnalyticsRows(rows);
        }
      } catch (err: unknown) {
        if (alive) {
          setError(err instanceof Error ? err.message : 'Failed to load member analytics');
        }
      } finally {
        if (alive) {
          setLoading(false);
        }
      }
    };

    void loadMemberAnalytics();

    return () => {
      alive = false;
    };
  }, [circleId, userId]);

  const timelineRows = useMemo<MemberAnalyticsRow[]>(() => {
    return [...analyticsRows]
      .filter((row) => row.member_id === userId)
      .sort(monthSorterDesc);
  }, [analyticsRows, userId]);

  const sovereigntyProjection = useMemo<SovereigntyProjection>(() => {
    const groupLiquidity = timelineRows
      .filter((row) => row.tx_type === 'PAYOUT' || row.tx_type === 'DELAYED_PAYOUT')
      .reduce((sum, row) => sum + Math.abs(row.amount), 0);

    const equivalentLoanInterest = Number((LOAN_PRINCIPAL * LOAN_APR * LOAN_TERM_YEARS).toFixed(2));
    const totalLoanRepayment = Number((LOAN_PRINCIPAL + equivalentLoanInterest).toFixed(2));
    const savingsVsLoan = Number((totalLoanRepayment - groupLiquidity).toFixed(2));

    return {
      groupLiquidity: Number(groupLiquidity.toFixed(2)),
      equivalentLoanPrincipal: LOAN_PRINCIPAL,
      equivalentLoanInterest,
      totalLoanRepayment,
      savingsVsLoan,
    };
  }, [timelineRows]);

  return (
    <section className="mx-auto w-full max-w-5xl space-y-6 p-4 md:p-8">
      <header className="space-y-2">
        <h2 className="text-2xl font-bold tracking-tight text-slate-900">WealthPath</h2>
        <p className="text-sm text-slate-600">
          Lifecycle timeline from the <code>member_analytics</code> view plus a Sovereignty Projection
          comparing community liquidity with a personal loan at 18% APR.
        </p>
      </header>

      {loading && <p className="text-sm text-slate-700">Loading member lifecycle…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!loading && !error && (
        <>
          <div className="grid gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm md:grid-cols-2">
            <div>
              <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
                Group Liquidity Accessed
              </h3>
              <p className="text-3xl font-bold text-emerald-600">
                {formatCurrency(sovereigntyProjection.groupLiquidity)}
              </p>
              <p className="mt-2 text-xs text-slate-500">
                Total payout liquidity delivered by the circle to this member.
              </p>
            </div>
            <div>
              <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
                Sovereignty Projection
              </h3>
              <ul className="space-y-1 text-sm text-slate-700">
                <li>
                  Equivalent loan principal: {formatCurrency(sovereigntyProjection.equivalentLoanPrincipal)}
                </li>
                <li>
                  Loan interest (18% APR): {formatCurrency(sovereigntyProjection.equivalentLoanInterest)}
                </li>
                <li>
                  Loan total repayment: {formatCurrency(sovereigntyProjection.totalLoanRepayment)}
                </li>
                <li className="font-semibold text-indigo-700">
                  Net sovereignty delta: {formatCurrency(sovereigntyProjection.savingsVsLoan)}
                </li>
              </ul>
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h3 className="mb-4 text-lg font-semibold text-slate-900">Contribution & Payout Timeline</h3>
            <ol className="relative border-s border-slate-200 ps-5">
              {timelineRows.map((row, index) => (
                <motion.li
                  key={row.entry_id}
                  initial={{ opacity: 0, x: -16 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.25, delay: index * 0.03 }}
                  className="mb-6 ms-2"
                >
                  <span className="absolute -start-1.5 mt-1.5 h-3 w-3 rounded-full bg-indigo-500" />
                  <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
                    <p className="text-xs uppercase tracking-wide text-slate-500">
                      Month {row.circle_month} • {row.tx_type}
                    </p>
                    <p className="text-sm font-medium text-slate-900">{formatCurrency(row.amount)}</p>
                    {row.note ? <p className="text-xs text-slate-600">{row.note}</p> : null}
                  </div>
                </motion.li>
              ))}
            </ol>
            {timelineRows.length === 0 && (
              <p className="text-sm text-slate-500">No lifecycle entries yet for this member.</p>
            )}
          </div>
        </>
      )}
    </section>
  );
};

export default WealthPath;

import React, { useEffect, useMemo, useState } from 'react';
import { LedgerEntry, MemberNetPosition } from '../types/ledger';
import { fetchLedger, settleArrears } from '../lib/api';
// Using shadcn/ui components for consistency
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

/**
 * ARCHITECTURAL DIRECTIVE:
 * 1. Fetch LedgerEntry[] and compute MemberNetPosition dynamically using useMemo.
 * 2. NEVER store financial balances in useState; always derive from the immutable ledger.
 * 3. Use 'principal_paid' and 'fee' logic for any settlement interactions.
 * 4. Display transaction history sorted by month DESC.
 * 5. Apply strict TypeScript typing; zero use of 'any'.
 */

interface SettlementApiResponse {
  status: string;
  principal_settled: number;
  fee_paid: number;
}

const isInflowForMember = (entry: LedgerEntry): boolean =>
  entry.tx_type === 'CONTRIBUTION' || entry.tx_type === 'LATE_CONTRIBUTION' || entry.tx_type === 'LATE_FEE';

const isOutflowForMember = (entry: LedgerEntry): boolean => entry.amount < 0;

export const MemberDashboard: React.FC<{ circleId: string; userId: string }> = ({ circleId, userId }) => {
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [settlementDebtId, setSettlementDebtId] = useState<string>('');
  const [cashReceived, setCashReceived] = useState<string>('');
  const [settlementMessage, setSettlementMessage] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    const loadLedger = async (): Promise<void> => {
      setLoading(true);
      setError(null);

      try {
        const entries = await fetchLedger(circleId);
        if (mounted) {
          setLedger(entries);
        }
      } catch (err: unknown) {
        if (mounted) {
          const message = err instanceof Error ? err.message : 'Failed to load ledger';
          setError(message);
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };

    void loadLedger();

    return () => {
      mounted = false;
    };
  }, [circleId]);

  const sortedLedger = useMemo<LedgerEntry[]>(() => {
    return [...ledger].sort((a, b) => {
      if (b.circle_month !== a.circle_month) {
        return b.circle_month - a.circle_month;
      }
      return b.timestamp.localeCompare(a.timestamp);
    });
  }, [ledger]);

  const memberEntries = useMemo<LedgerEntry[]>(
    () => sortedLedger.filter((entry) => entry.member_id === userId || entry.intended_for === userId),
    [sortedLedger, userId],
  );

  const netPosition = useMemo<MemberNetPosition>(() => {
    const contributed = memberEntries
      .filter(isInflowForMember)
      .reduce((sum, entry) => sum + entry.amount, 0);

    const received = memberEntries
      .filter(isOutflowForMember)
      .reduce((sum, entry) => sum + Math.abs(entry.amount), 0);

    const penalties = memberEntries
      .filter((entry) => entry.tx_type === 'LATE_FEE')
      .reduce((sum, entry) => sum + entry.amount, 0);

    const pendingArrears = memberEntries
      .filter((entry) => entry.tx_type === 'ARREARS' && entry.status === 'pending')
      .reduce((sum, entry) => sum + entry.amount, 0);

    return {
      member_id: userId,
      contributed: Number(contributed.toFixed(2)),
      received: Number(received.toFixed(2)),
      penalties: Number(penalties.toFixed(2)),
      net: Number((contributed - received).toFixed(2)),
      pending_arrears: Number(pendingArrears.toFixed(2)),
    };
  }, [memberEntries, userId]);

  const handleSettle = async (): Promise<void> => {
    setSettlementMessage(null);

    const parsedCash = Number(cashReceived);
    if (!Number.isFinite(parsedCash) || parsedCash <= 0) {
      setSettlementMessage('Enter a valid positive cash amount.');
      return;
    }

    try {
      const response = (await settleArrears(
        userId,
        parsedCash,
        settlementDebtId.trim() ? settlementDebtId.trim() : undefined,
      )) as SettlementApiResponse;

      setSettlementMessage(
        `Settlement successful. Principal paid: $${response.principal_settled.toFixed(2)}, fee: $${response.fee_paid.toFixed(2)}.`,
      );

      const refreshed = await fetchLedger(circleId);
      setLedger(refreshed);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Settlement failed';
      setSettlementMessage(message);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Member Dashboard</CardTitle>
      </CardHeader>
      <CardContent>
        {loading && <p>Loading ledger…</p>}
        {error && <p className="text-red-600">{error}</p>}

        {!loading && !error && (
          <>
            <div className="mb-4 grid grid-cols-2 gap-2 text-sm">
              <p>
                <strong>Contributed:</strong> ${netPosition.contributed.toFixed(2)}
              </p>
              <p>
                <strong>Received:</strong> ${netPosition.received.toFixed(2)}
              </p>
              <p>
                <strong>Penalties:</strong> ${netPosition.penalties.toFixed(2)}
              </p>
              <p>
                <strong>Net:</strong> ${netPosition.net.toFixed(2)}
              </p>
              <p>
                <strong>Pending arrears:</strong> ${netPosition.pending_arrears.toFixed(2)}
              </p>
            </div>

            <div className="mb-6 space-y-2 rounded border p-3">
              <h3 className="font-semibold">Settle arrears</h3>
              <label className="block text-sm">
                Debt ID (optional)
                <input
                  className="mt-1 w-full rounded border p-2"
                  value={settlementDebtId}
                  onChange={(e) => setSettlementDebtId(e.target.value)}
                  placeholder="debt UUID"
                />
              </label>
              <label className="block text-sm">
                Cash received
                <input
                  className="mt-1 w-full rounded border p-2"
                  value={cashReceived}
                  onChange={(e) => setCashReceived(e.target.value)}
                  placeholder="0.00"
                  inputMode="decimal"
                />
              </label>
              <button className="rounded bg-black px-3 py-2 text-white" onClick={() => void handleSettle()}>
                Submit settlement
              </button>
              {settlementMessage && <p className="text-sm">{settlementMessage}</p>}
            </div>

            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Month</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Amount</TableHead>
                  <TableHead>Note</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {memberEntries.map((entry) => (
                  <TableRow key={entry.id}>
                    <TableCell>{entry.circle_month}</TableCell>
                    <TableCell>{entry.tx_type}</TableCell>
                    <TableCell>{entry.status}</TableCell>
                    <TableCell>${entry.amount.toFixed(2)}</TableCell>
                    <TableCell>{entry.note}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        )}
      </CardContent>
    </Card>
  );
};

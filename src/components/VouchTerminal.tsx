import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import { Shield, CheckCircle, Loader2, AlertCircle } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { fetchProspectDetails, submitVouch } from '@/lib/api';

export const VoucherTerminal: React.FC = () => {
  const { prospectId } = useParams<{ prospectId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [vouchSuccess, setVouchSuccess] = React.useState(false);

  const {
    data: prospect,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['prospect', prospectId],
    queryFn: () => fetchProspectDetails(prospectId as string),
    enabled: Boolean(prospectId),
    retry: false,
  });

  const vouchMutation = useMutation({
    mutationFn: () => submitVouch(prospectId as string),
    onSuccess: async () => {
      setVouchSuccess(true);
      await queryClient.invalidateQueries({ queryKey: ['prospect', prospectId] });
      window.setTimeout(() => navigate('/dashboard'), 2000);
    },
  });

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-indigo-600" />
      </div>
    );
  }

  if (error || !prospect) {
    return (
      <Alert variant="destructive" className="mx-auto mt-8 max-w-lg">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>
          {error instanceof Error ? error.message : 'Invalid or expired vouch link.'}
        </AlertDescription>
      </Alert>
    );
  }

  const isEligible = prospect.tier1_status === 'pending';

  return (
    <div className="mx-auto max-w-lg p-4 md:p-8">
      <Card className="border-slate-200 shadow-lg">
        <CardHeader>
          <CardTitle className="flex items-center space-x-2">
            <Shield className="h-6 w-6 text-indigo-600" />
            <span>Vouch Request</span>
          </CardTitle>
          <CardDescription>
            {prospect.name} is asking you to vouch for them in the Pelo community.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="rounded-lg bg-slate-50 p-4">
            <p className="text-sm text-slate-600">
              <span className="font-semibold">Prospect:</span> {prospect.name}
            </p>
            <p className="text-sm text-slate-600">
              <span className="font-semibold">Current status:</span>{' '}
              {prospect.tier1_status === 'pending' ? (
                <span className="text-yellow-600">Awaiting vouches</span>
              ) : (
                <span className="text-green-600">Already verified</span>
              )}
            </p>
          </div>

          {!isEligible && (
            <Alert>
              <CheckCircle className="h-4 w-4 text-green-600" />
              <AlertDescription>
                This person already has the required vouches or is already verified.
              </AlertDescription>
            </Alert>
          )}

          <AnimatePresence>
            {vouchSuccess ? (
              <motion.div
                initial={{ scale: 0.8, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                className="flex flex-col items-center space-y-2 rounded-lg bg-green-50 p-6"
              >
                <Shield className="h-12 w-12 text-green-600" />
                <p className="text-center text-lg font-semibold text-green-800">Vouch confirmed!</p>
                <p className="text-center text-sm text-green-600">
                  You’ve strengthened the community. Redirecting…
                </p>
              </motion.div>
            ) : (
              <motion.div initial={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-4">
                <Button
                  onClick={() => vouchMutation.mutate()}
                  disabled={vouchMutation.isPending || !isEligible}
                  className="w-full"
                  variant="default"
                >
                  {vouchMutation.isPending ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Shield className="mr-2 h-4 w-4" />
                  )}
                  Confirm Vouch
                </Button>
                {vouchMutation.isError && (
                  <Alert variant="destructive">
                    <AlertCircle className="h-4 w-4" />
                    <AlertDescription>
                      {vouchMutation.error instanceof Error
                        ? vouchMutation.error.message
                        : 'Failed to record vouch. Please try again.'}
                    </AlertDescription>
                  </Alert>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </CardContent>
      </Card>
    </div>
  );
};

export const VouchTerminal = VoucherTerminal;
export default VoucherTerminal;

import React, { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import { Check, CheckCircle, Copy, Fingerprint, Landmark, Link as LinkIcon, Loader2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { fetchVerificationStatus, submitVerification } from '@/lib/api';
import { VerificationStatusResponse } from '@/types/identity';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';

const SocialProofStep = ({ userId }: { userId: string }) => {
  const [generatedLink, setGeneratedLink] = React.useState<string | null>(null);
  const [isGenerating, setIsGenerating] = React.useState(false);
  const [copySuccess, setCopySuccess] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const generateVouchLink = async () => {
    setIsGenerating(true);
    setCopySuccess(false);
    setError(null);
    try {
      const response = await fetch('/api/identity/request-vouch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!response.ok) throw new Error('Failed to generate link');
      const data = (await response.json()) as { prospect_id?: string };

      const prospectId = data.prospect_id ?? userId;
      if (!prospectId) {
        throw new Error('Missing prospect identifier');
      }

      const link = `${window.location.origin}/vouch/${prospectId}`;
      setGeneratedLink(link);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to generate link');
    } finally {
      setIsGenerating(false);
    }
  };

  const copyToClipboard = async () => {
    if (!generatedLink) return;
    await navigator.clipboard.writeText(generatedLink);
    setCopySuccess(true);
    window.setTimeout(() => setCopySuccess(false), 2000);
  };

  return (
    <div className="space-y-4">
      {!generatedLink ? (
        <Button onClick={() => void generateVouchLink()} disabled={isGenerating} className="w-full">
          {isGenerating ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <LinkIcon className="mr-2 h-4 w-4" />}
          Generate Shareable Link
        </Button>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-slate-600">Share this link with two active members via WhatsApp or SMS:</p>
          <div className="flex items-center space-x-2">
            <Input readOnly value={generatedLink} className="font-mono text-xs" />
            <Button variant="outline" size="icon" onClick={() => void copyToClipboard()}>
              {copySuccess ? <Check className="h-4 w-4 text-green-600" /> : <Copy className="h-4 w-4" />}
            </Button>
          </div>
          <p className="text-xs text-slate-500">
            Once both members confirm, your Tier 1 status will be verified automatically.
          </p>
        </div>
      )}

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
    </div>
  );
};

const SovereignIdStep = ({ onComplete }: { onComplete: () => void }) => {
  const [isProcessing, setIsProcessing] = React.useState(false);
  const [error, setError] = React.useState('');

  const startVerification = async () => {
    setError('');
    setIsProcessing(true);
    try {
      const providerRef = `mock-ref-${Date.now()}`;
      await submitVerification({ tier: 2, provider_ref: providerRef });
      onComplete();
    } catch (_err) {
      setError('Verification failed. Please try again.');
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        Verify your identity with a government ID and liveness check. This is required to join circles with
        a pot larger than $500.
      </p>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <Button onClick={() => void startVerification()} disabled={isProcessing} className="w-full">
        {isProcessing ? (
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        ) : (
          <Fingerprint className="mr-2 h-4 w-4" />
        )}
        Start ID Verification
      </Button>
    </div>
  );
};

const FinancialProofStep = ({ onComplete }: { onComplete: () => void }) => {
  const [isLinking, setIsLinking] = React.useState(false);
  const [error, setError] = React.useState('');

  const startPlaidLink = async () => {
    setError('');
    setIsLinking(true);
    try {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      onComplete();
    } catch (_err) {
      setError('Failed to link bank account.');
    } finally {
      setIsLinking(false);
    }
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        Link a bank account to join unlimited-capital circles. Your account is used only for verification;
        we never store credentials.
      </p>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <Button onClick={() => void startPlaidLink()} disabled={isLinking} className="w-full">
        {isLinking ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Landmark className="mr-2 h-4 w-4" />}
        Connect Bank Account
      </Button>
    </div>
  );
};

const StepIcon = ({ status, isActive }: { status: string; isActive: boolean }) => {
  if (status === 'verified') return <CheckCircle className="h-5 w-5 text-green-600" />;
  if (status === 'pending') return <Loader2 className="h-5 w-5 animate-spin text-yellow-600" />;
  if (isActive) return <div className="h-5 w-5 rounded-full bg-indigo-600" />;
  return <div className="h-5 w-5 rounded-full bg-slate-300" />;
};

export const OnboardingStepper: React.FC = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [activeStep, setActiveStep] = React.useState<1 | 2 | 3>(1);


  const {
    data: status,
    isLoading,
    error,
  } = useQuery<VerificationStatusResponse>({
    queryKey: ['identityStatus'],
    queryFn: fetchVerificationStatus,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (
        data?.tier1_status === 'pending' ||
        data?.tier2_status === 'pending' ||
        data?.tier3_status === 'pending'
      ) {
        return 3000;
      }
      return false;
    },
  });

  useEffect(() => {
    if (!status) {
      return;
    }

    if (status.tier1_status === 'verified') {
      if (status.tier2_status === 'verified') {
        setActiveStep(3);
      } else {
        setActiveStep(2);
      }
    } else {
      setActiveStep(1);
    }
  }, [status]);

  useEffect(() => {
    if (
      status?.tier1_status === 'verified' &&
      status?.tier2_status === 'verified' &&
      status?.tier3_status === 'verified'
    ) {
      navigate('/dashboard', { replace: true });
    }
  }, [status, navigate]);

  if (isLoading) {
    return (
      <div className="mx-auto max-w-lg space-y-4 p-8">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto max-w-lg p-8">
        <Alert variant="destructive">
          <AlertDescription>Failed to load verification status. Please refresh.</AlertDescription>
        </Alert>
      </div>
    );
  }

  if (!status) {
    return null;
  }

  const steps: {
    id: 1 | 2 | 3;
    title: string;
    description: string;
    status: string;
    component: React.ReactNode;
  }[] = [
    {
      id: 1,
      title: 'Social Proof',
      description: 'Get vouched for by two members',
      status: status.tier1_status,
      component: (
        <SocialProofStep userId={status.user_id} />
      ),
    },
    {
      id: 2,
      title: 'Sovereign ID',
      description: 'Verify your identity',
      status: status.tier2_status,
      component: (
        <SovereignIdStep onComplete={() => queryClient.invalidateQueries({ queryKey: ['identityStatus'] })} />
      ),
    },
    {
      id: 3,
      title: 'Financial Proof',
      description: 'Link a bank account',
      status: status.tier3_status,
      component: (
        <FinancialProofStep onComplete={() => queryClient.invalidateQueries({ queryKey: ['identityStatus'] })} />
      ),
    },
  ];

  const isAnyPending = steps.some((step) => step.status === 'pending');

  return (
    <div className="relative mx-auto max-w-2xl p-4 md:p-8">
      <AnimatePresence>
        {isAnyPending && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-white/80 backdrop-blur-sm"
          >
            <div className="text-center">
              <Loader2 className="mx-auto h-8 w-8 animate-spin text-indigo-600" />
              <p className="mt-2 text-sm font-medium text-slate-700">Processing verification…</p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <Card className="border-slate-200 shadow-lg">
        <CardHeader>
          <CardTitle className="text-2xl font-bold text-slate-900">Welcome to Pelo Global Solutions</CardTitle>
          <CardDescription>Complete the steps below to unlock higher-value circles.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="mb-8 flex items-center justify-between">
            {steps.map((step, index) => (
              <React.Fragment key={step.id}>
                <div className="flex flex-col items-center">
                  <StepIcon status={step.status} isActive={activeStep === step.id} />
                  <span className="mt-2 text-xs font-medium text-slate-600">{step.title}</span>
                </div>
                {index < steps.length - 1 && <div className="h-[2px] w-16 bg-slate-300" />}
              </React.Fragment>
            ))}
          </div>

          <AnimatePresence mode="wait">
            <motion.div
              key={activeStep}
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: 0.2 }}
            >
              {steps.find((s) => s.id === activeStep)?.component}
            </motion.div>
          </AnimatePresence>

          {steps.find((s) => s.id === activeStep)?.status === 'pending' && (
            <Alert className="mt-4">
              <Loader2 className="h-4 w-4 animate-spin" />
              <AlertDescription>
                Your verification is being processed. This may take a few minutes.
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default OnboardingStepper;

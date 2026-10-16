import { ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { QueryBoundary } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Field, Input } from '@/components/ui/input';
import { Alert } from '@/components/ui/misc';
import {
  useConfirmTotp,
  useMfaStatus,
  useStartTotp,
  useStepUp,
} from '@/features/auth/api';
import { AccountLayout } from '@/features/orgs/orgs-pages';
import { errorMessage } from '@/lib/api/http';
import { t } from '@/lib/i18n';

const codePattern = '[0-9]{6}';

/** Asks for a fresh authenticator code, then calls `onDone` (the API accepts it for 10 minutes). */
export function StepUpDialog({
  onDone,
  onOpenChange,
  open,
}: {
  onDone: () => void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
}) {
  const stepUp = useStepUp();
  const [code, setCode] = useState('');
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          stepUp.reset();
          setCode('');
        }
        onOpenChange(next);
      }}
    >
      <DialogContent size="sm">
        <DialogHeader>
          <DialogTitle>{t('Confirm it is you')}</DialogTitle>
          <DialogDescription>
            {t(
              'Enter the 6-digit code from your authenticator app to continue.',
            )}
          </DialogDescription>
        </DialogHeader>
        <form
          id="step-up-form"
          onSubmit={(event) => {
            event.preventDefault();
            stepUp.mutate(code, {
              onSuccess: () => {
                setCode('');
                onDone();
              },
            });
          }}
        >
          <Field
            htmlFor="step-up-code"
            label={t('Authenticator code')}
            error={stepUp.isError ? errorMessage(stepUp.error) : undefined}
          >
            <Input
              id="step-up-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern={codePattern}
              maxLength={6}
              required
              value={code}
              onChange={(event) => setCode(event.target.value)}
            />
          </Field>
        </form>
        <DialogFooter>
          <Button asChild variant="ghost">
            <Link to="/me/security">{t('Set up an authenticator')}</Link>
          </Button>
          <Button onClick={() => onOpenChange(false)}>{t('Back')}</Button>
          <Button
            type="submit"
            form="step-up-form"
            variant="primary"
            loading={stepUp.isPending}
            disabled={code.length !== 6}
          >
            {t('Confirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** TOTP enrolment. Approving a payment needs this second factor. */
export function SecurityPage() {
  const status = useMfaStatus();
  const start = useStartTotp();
  const confirm = useConfirmTotp();
  const [code, setCode] = useState('');
  // shortcut: the otpauth URI is shown as text (no QR library is installed); add a QR code if one lands.
  let secret: string | null = null;
  try {
    if (start.data)
      secret = new URL(start.data.otpauthUri).searchParams.get('secret');
  } catch {
    // The full URI is still shown below.
  }

  return (
    <AccountLayout>
      <Page
        width="narrow"
        title={t('Security')}
        description={t(
          'A second factor is required to approve payments. Use any authenticator app.',
        )}
      >
        <QueryBoundary query={status}>
          {(data) => (
            <Card>
              <CardHeader title={t('Authenticator app')} />
              <CardContent className="grid gap-4">
                {confirm.data ? (
                  <Alert tone="success" title={t('Authenticator enabled')}>
                    {t('Save these recovery codes now. They are shown once:')}{' '}
                    <span className="num" data-testid="recovery-codes">
                      {confirm.data.recoveryCodes.join(' ')}
                    </span>
                  </Alert>
                ) : data.factors.length > 0 ? (
                  <Alert tone="success" title={t('Authenticator enabled')}>
                    <ShieldCheck className="inline size-3.5" aria-hidden />{' '}
                    {data.factors.map((factor) => factor.label).join(', ')}
                  </Alert>
                ) : start.data ? (
                  <form
                    className="grid gap-3"
                    onSubmit={(event) => {
                      event.preventDefault();
                      confirm.mutate(
                        { factorId: start.data.factorId, code },
                        { onSuccess: () => setCode('') },
                      );
                    }}
                  >
                    <p className="text-sm text-muted-foreground">
                      {t(
                        'Add this key to your authenticator app, then enter the code it shows.',
                      )}
                    </p>
                    <code
                      className="num break-all text-sm"
                      data-testid="totp-secret"
                    >
                      {secret}
                    </code>
                    <code className="break-all text-xs text-muted-foreground">
                      {start.data.otpauthUri}
                    </code>
                    <Field
                      htmlFor="totp-code"
                      label={t('Authenticator code')}
                      error={
                        confirm.isError
                          ? errorMessage(confirm.error)
                          : undefined
                      }
                    >
                      <Input
                        id="totp-code"
                        inputMode="numeric"
                        autoComplete="one-time-code"
                        pattern={codePattern}
                        maxLength={6}
                        required
                        value={code}
                        onChange={(event) => setCode(event.target.value)}
                      />
                    </Field>
                    <Button
                      type="submit"
                      variant="primary"
                      loading={confirm.isPending}
                      disabled={code.length !== 6}
                    >
                      {t('Enable authenticator')}
                    </Button>
                  </form>
                ) : (
                  <div>
                    <Button
                      variant="primary"
                      loading={start.isPending}
                      onClick={() => start.mutate()}
                    >
                      {t('Set up authenticator app')}
                    </Button>
                    {start.isError && (
                      <Alert tone="danger" title={t('Could not start set-up')}>
                        {errorMessage(start.error)}
                      </Alert>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </QueryBoundary>
      </Page>
    </AccountLayout>
  );
}

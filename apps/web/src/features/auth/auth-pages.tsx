import { CircleDollarSign, MailCheck } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  Link,
  Navigate,
  Outlet,
  useLocation,
  useNavigate,
  useSearchParams,
} from 'react-router-dom';

import { ErrorState } from '@/components/feedback';
import { Button } from '@/components/ui/button';
import { Field, Input } from '@/components/ui/input';
import { Alert } from '@/components/ui/misc';
import {
  useMe,
  useRequestMagicLink,
  useVerifyMagicLink,
} from '@/features/auth/api';
import { errorMessage, isApiError } from '@/lib/api/http';
import { mockApiEnabled } from '@/lib/env';
import { t } from '@/lib/i18n';

const returnKey = 'treasurypilot.return-to';

function FullPageSpinner({ label }: { label: string }) {
  return (
    <div className="grid min-h-dvh place-items-center" role="status">
      <div className="flex items-center gap-3 text-base text-muted-foreground">
        <span className="size-4 animate-spin rounded-full border-2 border-border-strong border-t-primary" />
        {label}
      </div>
    </div>
  );
}

/** Wraps every signed-in route. Remembers where the user was heading. */
export function AuthGuard() {
  const me = useMe();
  const location = useLocation();
  if (me.isPending)
    return <FullPageSpinner label={t('Loading TreasuryPilot…')} />;
  if (me.isError) {
    return (
      <div className="grid min-h-dvh place-items-center">
        <ErrorState error={me.error} onRetry={() => void me.refetch()} />
      </div>
    );
  }
  if (!me.data) {
    try {
      window.sessionStorage.setItem(
        returnKey,
        `${location.pathname}${location.search}`,
      );
    } catch {
      /* the user lands on the default page instead */
    }
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}

function takeReturnPath(): string {
  try {
    const path = window.sessionStorage.getItem(returnKey);
    window.sessionStorage.removeItem(returnKey);
    return path && path !== '/login' ? path : '/';
  } catch {
    return '/';
  }
}

function AuthFrame({ children }: { children: ReactNode }) {
  return (
    <main className="grid min-h-dvh place-items-center bg-background px-4 py-10">
      <div className="w-full max-w-sm">
        <Link
          to="/login"
          className="mb-8 flex items-center gap-2.5 text-lg font-semibold"
        >
          <span className="grid size-8 place-items-center rounded-md bg-primary text-primary-foreground">
            <CircleDollarSign className="size-4" aria-hidden="true" />
          </span>
          TreasuryPilot
        </Link>
        {children}
        <p className="mt-8 text-xs text-subtle-foreground">
          {t(
            'Human-authorized, policy-enforced treasury operations. Your wallet keys never leave your wallet.',
          )}
        </p>
      </div>
    </main>
  );
}

export function LoginPage() {
  const me = useMe();
  const request = useRequestMagicLink();
  const [email, setEmail] = useState('');
  const [sentTo, setSentTo] = useState('');

  if (me.data) return <Navigate to={takeReturnPath()} replace />;

  if (sentTo) {
    return (
      <AuthFrame>
        <MailCheck className="size-6 text-primary" aria-hidden="true" />
        <h1 className="mt-3 text-2xl font-semibold">{t('Check your email')}</h1>
        <p className="mt-2 text-base text-muted-foreground">
          {t('We sent a sign-in link to')}{' '}
          <strong className="font-medium text-foreground">{sentTo}</strong>.{' '}
          {t('It works once and expires in 15 minutes.')}
        </p>
        {mockApiEnabled && (
          <Alert
            tone="warning"
            className="mt-5"
            title={t('Mock API: no email is sent')}
          >
            <Link
              className="font-medium underline"
              to={`/verify?token=mock.${encodeURIComponent(sentTo)}`}
            >
              {t('Open the sign-in link')}
            </Link>
          </Alert>
        )}
        <div className="mt-6 flex gap-2">
          <Button
            loading={request.isPending}
            onClick={() => request.mutate(sentTo)}
          >
            {t('Send again')}
          </Button>
          <Button variant="ghost" onClick={() => setSentTo('')}>
            {t('Use a different email')}
          </Button>
        </div>
      </AuthFrame>
    );
  }

  return (
    <AuthFrame>
      <h1 className="text-2xl font-semibold">{t('Sign in')}</h1>
      <p className="mt-2 text-base text-muted-foreground">
        {t(
          'Enter your work email and we will send you a sign-in link. No password.',
        )}
      </p>
      <form
        className="mt-6 grid gap-4"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          const address = email.trim().toLowerCase();
          request.mutate(address, { onSuccess: () => setSentTo(address) });
        }}
      >
        <Field
          htmlFor="email"
          label={t('Work email')}
          error={request.isError ? errorMessage(request.error) : undefined}
        >
          <Input
            id="email"
            type="email"
            autoComplete="email"
            autoFocus
            required
            placeholder="you@company.com"
            value={email}
            aria-invalid={request.isError}
            aria-describedby={request.isError ? 'email-error' : undefined}
            onChange={(event) => setEmail(event.target.value)}
          />
        </Field>
        <Button
          type="submit"
          variant="primary"
          size="lg"
          loading={request.isPending}
        >
          {t('Send sign-in link')}
        </Button>
      </form>
      {import.meta.env.VITE_OIDC_ENABLED === 'true' && (
        <div className="mt-4 border-t border-border pt-4">
          <Button asChild size="lg" className="w-full">
            <a
              href={`${(import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/$/, '')}/v1/auth/oidc/start`}
            >
              {t('Continue with company SSO')}
            </a>
          </Button>
        </div>
      )}
      {mockApiEnabled && (
        <Alert tone="neutral" className="mt-6" title={t('Demo data')}>
          {t('Sign in as')}{' '}
          <button
            type="button"
            className="num font-medium underline"
            onClick={() => setEmail('linh@northwind.test')}
          >
            linh@northwind.test
          </button>{' '}
          {t(
            'to open the seeded organization. Any other email starts with an empty account.',
          )}
        </Alert>
      )}
    </AuthFrame>
  );
}

export function VerifyPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const verify = useVerifyMagicLink();
  const started = useRef(false);
  const token = params.get('token') ?? '';
  const { mutate } = verify;

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    mutate(token, {
      onSuccess: () => navigate(takeReturnPath(), { replace: true }),
    });
  }, [mutate, navigate, token]);

  if (verify.isError) {
    const expired = isApiError(verify.error, 'TOKEN_EXPIRED');
    return (
      <AuthFrame>
        <h1 className="text-2xl font-semibold">
          {expired ? t('This link has expired') : t('This link is not valid')}
        </h1>
        <p className="mt-2 text-base text-muted-foreground" role="alert">
          {errorMessage(verify.error)}
        </p>
        <Button asChild variant="primary" className="mt-6">
          <Link to="/login">{t('Request a new link')}</Link>
        </Button>
      </AuthFrame>
    );
  }
  return <FullPageSpinner label={t('Signing you in…')} />;
}

/** `/`: the first organization, or the organization list when there is none. */
export function HomeRedirect() {
  const me = useMe();
  const first = me.data?.memberships[0];
  return <Navigate to={first ? `/o/${first.orgId}` : '/orgs'} replace />;
}

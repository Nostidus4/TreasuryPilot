import { AlertTriangle } from 'lucide-react';

import { Button } from '@/components/ui/button';

type ErrorStateProps = {
  message?: string;
  onRetry?: () => void;
};

export function ErrorState({
  message = 'Something went wrong.',
  onRetry,
}: ErrorStateProps) {
  return (
    <section
      role="alert"
      className="rounded-2xl border border-amber-200 bg-amber-50 p-6"
    >
      <AlertTriangle aria-hidden="true" className="text-amber-700" />
      <h2 className="mt-3 font-semibold text-amber-950">
        We could not load this view
      </h2>
      <p className="mt-1 text-sm text-amber-900">{message}</p>
      {onRetry ? (
        <Button variant="outline" className="mt-4" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </section>
  );
}

import { Scale, Sparkles } from 'lucide-react';
import type { ReactNode } from 'react';

import { Badge } from '@/components/ui/badge';
import type { Validation } from '@/lib/api/types';
import { formatRelative } from '@/lib/format';
import { t } from '@/lib/i18n';
import type { StatusMeta } from '@/lib/status';
import { cn } from '@/lib/utils';

/** Status = dot + words, never colour alone. Wording comes from lib/status. */
export function StatusBadge({
  className,
  meta,
}: {
  className?: string;
  meta: StatusMeta;
}) {
  return (
    <Badge tone={meta.tone} className={className}>
      <span
        aria-hidden="true"
        className={cn(
          'size-1.5 rounded-full bg-current',
          meta.live && 'animate-pulse-dot',
        )}
      />
      {meta.label}
    </Badge>
  );
}

/**
 * AI-written text always sits in this box, labelled (M16-D5).
 * It renders plain text only: model output is never treated as markup.
 */
export function AiExplanation({
  children,
  generatedAt,
  model,
  title,
}: {
  children: ReactNode;
  generatedAt?: string;
  model?: string;
  title?: string;
}) {
  return (
    <aside
      aria-label={t('AI explanation')}
      className="rounded-lg border border-ai-border bg-ai-muted p-3"
    >
      <p className="flex items-center gap-1.5 text-xs font-medium text-ai-foreground">
        <Sparkles className="size-3.5" aria-hidden="true" />
        {title ?? t('AI explanation')}
        <span className="font-normal text-ai-foreground/80">
          · {t('not a policy decision')}
        </span>
      </p>
      <div className="mt-1.5 whitespace-pre-line text-base text-foreground">
        {children}
      </div>
      {(model || generatedAt) && (
        <p className="mt-2 text-xs text-muted-foreground">
          {model}
          {model && generatedAt && ' · '}
          {generatedAt && formatRelative(generatedAt)}
        </p>
      )}
    </aside>
  );
}

const decisionTone = {
  ALLOW: 'success',
  WARN: 'warning',
  NEEDS_APPROVAL: 'warning',
  DENY: 'danger',
} as const;

const decisionLabel = {
  ALLOW: 'Allow',
  WARN: 'Warning',
  NEEDS_APPROVAL: 'Needs approval',
  DENY: 'Deny',
} as const;

/** Validator reason codes: the authoritative decision (BR-057). */
export function PolicyDecision({ validations }: { validations: Validation[] }) {
  return (
    <section
      aria-label={t('Policy decision')}
      className="rounded-lg border bg-surface"
    >
      <p className="flex items-center gap-1.5 border-b px-3 py-2 text-xs font-medium text-foreground">
        <Scale className="size-3.5" aria-hidden="true" />
        {t('Policy decision')}
        <span className="font-normal text-muted-foreground">
          · {t('authoritative, from the validator')}
        </span>
      </p>
      <ul className="divide-y">
        {validations.map((validation) => (
          <li
            key={`${validation.code}-${validation.stepId ?? ''}`}
            className="flex items-start gap-3 px-3 py-2"
          >
            <Badge
              tone={decisionTone[validation.decision]}
              className="mt-0.5 w-28 shrink-0 justify-center"
            >
              {t(decisionLabel[validation.decision])}
            </Badge>
            <div className="min-w-0">
              <p className="num text-xs text-muted-foreground">
                {validation.code}
              </p>
              <p className="text-base">{validation.message}</p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

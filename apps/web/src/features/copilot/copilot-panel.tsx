import { ArrowUp, Sparkles } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useLocation } from 'react-router-dom';

import { AiExplanation } from '@/components/domain/status';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogDescription,
  DialogTitle,
  SheetContent,
} from '@/components/ui/dialog';
import { Alert, Skeleton } from '@/components/ui/misc';
import { askCopilot, createCopilotThread } from '@/features/operations/api';
import { useOrgScope } from '@/features/orgs/org-scope';
import { errorMessage } from '@/lib/api/http';
import type { CopilotMessage } from '@/lib/api/types';
import { t } from '@/lib/i18n';

function suggestionsFor(pathname: string): string[] {
  if (pathname.includes('/plans')) {
    return [
      t('What will the current plan pay, and in what order?'),
      t('Why is Orbit Telecom paid early?'),
    ];
  }
  if (pathname.includes('/review') || pathname.includes('/requests')) {
    return [t('Why is LL-2026-512 held?'), t('What does the next plan pay?')];
  }
  return [
    t('How much liquidity is above the buffer?'),
    t('Why is LL-2026-512 held?'),
    t('What does the next plan pay?'),
  ];
}

/**
 * Copilot (F-140): read-only answers with citations. Every answer sits in an
 * "AI explanation" box; the panel cannot approve, sign or move funds.
 */
export function CopilotPanel({
  onOpenChange,
  open,
}: {
  onOpenChange: (open: boolean) => void;
  open: boolean;
}) {
  const scope = useOrgScope();
  const location = useLocation();
  const [messages, setMessages] = useState<CopilotMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const threadId = useRef<string>();
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: 'end' });
  }, [messages, pending]);

  const ask = async (text: string) => {
    const question = text.trim();
    if (!question || pending) return;
    setDraft('');
    setError('');
    setPending(true);
    setMessages((current) => [
      ...current,
      {
        id: `local-${current.length}`,
        role: 'user',
        content: question,
        citations: [],
      },
    ]);
    try {
      threadId.current ??= (await createCopilotThread(scope.orgId)).threadId;
      const { message } = await askCopilot(scope.orgId, threadId.current, {
        text: question,
        treasuryId: scope.treasuryId,
      });
      setMessages((current) => [...current, message]);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setPending(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void ask(draft);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <SheetContent width="md">
        <header className="border-b px-4 py-3 pr-12">
          <DialogTitle className="flex items-center gap-2 text-lg font-semibold">
            <Sparkles className="size-4 text-ai" aria-hidden="true" />
            {t('Treasury Copilot')}
          </DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            {t(
              'Answers questions from your treasury data. It cannot approve, sign or move funds.',
            )}
          </DialogDescription>
        </header>

        <div
          className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4"
          aria-live="polite"
        >
          {messages.length === 0 && (
            <div>
              <p className="text-sm text-muted-foreground">
                {t('Try one of these:')}
              </p>
              <div className="mt-2 grid gap-2">
                {suggestionsFor(location.pathname).map((suggestion) => (
                  <Button
                    key={suggestion}
                    className="h-auto justify-start whitespace-normal py-2 text-left"
                    onClick={() => void ask(suggestion)}
                  >
                    {suggestion}
                  </Button>
                ))}
              </div>
            </div>
          )}
          {messages.map((message) =>
            message.role === 'user' ? (
              <p
                key={message.id}
                className="ml-8 rounded-lg bg-muted px-3 py-2 text-base"
              >
                <span className="sr-only">{t('You asked:')} </span>
                {message.content}
              </p>
            ) : (
              <AiExplanation key={message.id}>
                {message.content}
                {message.citations.length > 0 && (
                  <span className="mt-2 flex flex-wrap gap-1.5">
                    {message.citations.map((citation, index) => (
                      <Link
                        key={citation.href}
                        to={citation.href}
                        onClick={() => onOpenChange(false)}
                        className="inline-flex items-center gap-1 rounded-sm border border-ai-border bg-surface px-1.5 py-0.5 text-xs font-medium text-ai-foreground hover:underline"
                      >
                        <span className="num">[{index + 1}]</span>
                        {citation.label}
                      </Link>
                    ))}
                  </span>
                )}
              </AiExplanation>
            ),
          )}
          {pending && (
            <div aria-label={t('Copilot is answering')}>
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="mt-2 h-4 w-1/2" />
            </div>
          )}
          {error && <Alert tone="danger">{error}</Alert>}
          <div ref={endRef} />
        </div>

        <form onSubmit={submit} className="flex gap-2 border-t p-3">
          <label htmlFor="copilot-input" className="sr-only">
            {t('Ask Copilot')}
          </label>
          <input
            id="copilot-input"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={t('Ask about balances, plans or held requests…')}
            autoComplete="off"
            className="h-9 min-w-0 flex-1 rounded-md border border-border-strong bg-surface px-3 text-base placeholder:text-subtle-foreground"
          />
          <Button
            type="submit"
            variant="primary"
            size="icon"
            aria-label={t('Send')}
            disabled={!draft.trim() || pending}
          >
            <ArrowUp aria-hidden="true" />
          </Button>
        </form>
      </SheetContent>
    </Dialog>
  );
}

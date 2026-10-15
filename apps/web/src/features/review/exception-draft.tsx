import { AiExplanation } from '@/components/domain/status';
import type { ExceptionAiDraft } from '@/lib/api/types';
import { t } from '@/lib/i18n';

export function ExceptionDraftView({ aiDraft }: { aiDraft: ExceptionAiDraft }) {
  const { summary, reasons, alternatives } = aiDraft.draft;
  return (
    <AiExplanation title={t('AI summary of the request')}>
      {aiDraft.source === 'TEMPLATE' && (
        <p className="text-xs text-muted-foreground">{t('Template')}</p>
      )}
      <p>{summary}</p>
      {reasons.length > 0 && (
        <ul className="mt-2 list-disc pl-5">
          {reasons.map((reason) => (
            <li key={reason.text}>{reason.text}</li>
          ))}
        </ul>
      )}
      {alternatives.length > 0 && (
        <>
          <p className="mt-2 font-medium">{t('Alternatives')}</p>
          <ul className="list-disc pl-5">
            {alternatives.map((alternative) => (
              <li key={alternative}>{alternative}</li>
            ))}
          </ul>
        </>
      )}
    </AiExplanation>
  );
}

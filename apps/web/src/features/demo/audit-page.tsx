import { useState } from 'react';

import { ListSkeleton } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { t } from '@/lib/i18n';

import { useScenario } from './api';
import { utcSeconds } from './format';
import { SecurityReportDialog } from './security-report';

export function DemoAuditPage() {
  const { data } = useScenario();
  const [report, setReport] = useState(false);
  if (!data) {
    return (
      <Page title={t('Audit')}>
        <ListSkeleton />
      </Page>
    );
  }
  const x = data.fixture.securityScenario;
  return (
    <Page
      title={t('Audit')}
      description={t('Stored evidence and the event trail')}
    >
      <Card>
        <CardHeader title={t('Security test evidence')} />
        <CardContent className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-base font-medium">{x.contractTestReference}</p>
            <p className="text-sm text-muted-foreground">
              {t('App block versus contract-negative test')}
            </p>
          </div>
          <span className="flex items-center gap-2">
            <Badge tone="warning">{t('Simulated')}</Badge>
            <Button size="sm" onClick={() => setReport(true)}>
              {t('View report')}
            </Button>
          </span>
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader
          title={t('Event trail')}
          description={`${t('Run')} ${data.state.runId}`}
        />
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('Event')}</TableHead>
              <TableHead>{t('Type')}</TableHead>
              <TableHead>{t('Scenario time')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {[...data.state.log].reverse().map((entry) => (
              <TableRow key={entry.id}>
                <TableCell className="num">{entry.id}</TableCell>
                <TableCell>{entry.type}</TableCell>
                <TableCell className="num">{utcSeconds(entry.at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
      <SecurityReportDialog
        data={data}
        open={report}
        onOpenChange={setReport}
      />
    </Page>
  );
}

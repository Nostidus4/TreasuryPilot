import path from 'node:path';

import { expect, test, type Page } from '@playwright/test';

/**
 * The 7m30 demo scenario (docs/demo), scenes 1 to 9, with the Director in a second window of
 * the same browser context (BroadcastChannel + shared storage), exactly as a recording runs.
 */
const samplePdf = path.resolve(
  import.meta.dirname,
  '../../../docs/demo/INV-CLOUD-042.pdf',
);

async function director(page: Page, action: string) {
  await page.getByTestId(`director-${action}`).click();
  if (action === 'RESET_DAY_D') {
    await page.getByTestId('director-RESET_DAY_D').click();
  }
}

async function switchRole(page: Page, name: string) {
  await page.getByTestId('demo-role-menu').click();
  await page.getByRole('menuitem', { name: new RegExp(`^${name}`) }).click();
  await expect(page.getByTestId('demo-role-menu')).toContainText(name);
}

test('demo scenario scenes 1 to 9', async ({ context }) => {
  const main = await context.newPage();
  const dir = await context.newPage();

  await dir.goto('demo/director');
  await expect(dir.getByTestId('director-panel')).toBeVisible();
  // Reset to a clean S0 first; the second click confirms.
  await dir.getByRole('button', { name: 'Reset', exact: true }).click();
  await dir.getByTestId('director-RESET_DAY_D').click();
  await expect(dir.getByTestId('director-stage')).toHaveText('S0');

  // Scene 1: Linh at Overview, no invoice A, task "Review cloud bill".
  await main.goto('./');
  await expect(main.getByTestId('demo-banner')).toContainText(
    'SIMULATION / SYNTHETIC DATA',
  );
  await expect(main.getByTestId('demo-banner')).toContainText(
    '2026-10-16 10:04:00 UTC',
  );
  await expect(main.getByTestId('demo-role-menu')).toContainText('Demo role');
  await expect(main.getByTestId('task-review-cloud-bill')).toContainText(
    'Review cloud bill',
  );
  await expect(main.getByText('INV-CLOUD-042')).toHaveCount(0);

  // Scene 2: T breakdown and O1.
  await main.getByRole('button', { name: 'View breakdown' }).click();
  const breakdown = main.getByTestId('treasury-t-breakdown');
  await expect(breakdown).toContainText('Balance');
  await expect(breakdown).toContainText('1,180');
  await expect(breakdown).toContainText('Payroll reserve');
  await expect(breakdown).toContainText('300');
  await expect(breakdown).toContainText('Floor');
  await expect(breakdown).toContainText('Free before A');
  await expect(breakdown).toContainText('780');
  await main.keyboard.press('Escape');
  await main.getByRole('button', { name: 'View O1 details' }).click();
  await expect(main.getByTestId('o1-detail')).toContainText('Spendable');
  await main.keyboard.press('Escape');
  await expect(main.getByText('1,280')).toBeVisible();
  await expect(main.getByText('3,280')).toBeVisible();
  await expect(main.getByTestId('obligation-b')).toContainText(
    'Approved / Scheduled',
  );

  // Scene 3: Controls > Mandate.
  await main.getByRole('link', { name: 'Controls' }).click();
  const mandate = main.getByTestId('mandate-summary');
  await expect(mandate).toContainText('Mandate v7');
  for (const action of ['WITHDRAW', 'REFILL', 'PAY', 'SUPPLY']) {
    await expect(mandate).toContainText(action);
  }
  await expect(mandate).toContainText('BLOCK');
  await expect(mandate).toContainText('Requires separate authorization');
  await expect(main.getByRole('button', { name: /edit/i })).toHaveCount(0);

  // Scene 4: upload, extract, review, submit, approve as An.
  await main.getByRole('link', { name: 'Invoices' }).click();
  await main.getByTestId('invoice-upload').click();
  await main.getByTestId('invoice-upload-input').setInputFiles({
    name: 'other.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('x'),
  });
  await expect(main.getByTestId('invoice-upload-error')).toContainText(
    'Unsupported in demo mode',
  );
  await main.getByTestId('invoice-upload-input').setInputFiles(samplePdf);
  await expect(main.getByTestId('invoice-extracting')).toContainText(
    'Extracting',
  );
  await expect(main.getByTestId('recorded-extraction')).toHaveText(
    'Recorded extraction',
  );
  await expect(main.getByTestId('invoice-source')).toContainText(
    'Invoice INV-CLOUD-042',
  );
  const submit = main.getByTestId('submit-invoice');
  await expect(submit).toBeDisabled();
  await main.getByTestId('invoice-reviewed').click();
  await submit.click();
  await expect(main.getByTestId('awaiting-approval')).toBeVisible();
  await expect(main.getByTestId('no-self-approval')).toContainText(
    'cannot approve its own',
  );
  await expect(
    main.getByRole('button', { name: 'Review & approve' }),
  ).toHaveCount(0);

  // A reload must not reset the scenario.
  await main.reload();
  await expect(main.getByTestId('awaiting-approval')).toBeVisible();

  await switchRole(main, 'An');
  await main.getByRole('button', { name: 'Review & approve' }).click();
  await expect(main.getByText('Simulated signature').first()).toBeVisible();
  await main.getByTestId('approval-confirm').click();
  await expect(main.getByTestId('approval-reference')).toHaveText(
    'SIM-APPROVAL-A-001',
  );
  await expect(main.getByTestId('plan-status')).toHaveText(
    'Ready - waiting for approved window',
  );
  await expect(main.getByTestId('invoice-header-status')).toHaveText(
    'Approved',
  );

  // Scene 5: plan.
  await main.getByRole('tab', { name: 'Plan' }).click();
  await expect(main.getByTestId('plan-alternatives')).toContainText('Standard');
  await expect(main.getByTestId('plan-alternatives')).toContainText('Selected');
  await expect(main.getByTestId('plan-alternatives')).toContainText(
    'Not selected',
  );
  await expect(main.getByTestId('estimated-benefit')).toContainText(
    'Synthetic assumptions',
  );
  await expect(main.getByTestId('estimated-net')).toContainText('≈18.05');
  await expect(main.getByTestId('plan-source')).toHaveText(
    'Deterministic scenario model',
  );
  await main.getByRole('button', { name: 'View funding breakdown' }).click();
  const shortage = main.getByTestId('liquidity-shortage');
  await expect(shortage).toContainText('980');
  await expect(shortage).toContainText('780');
  await expect(shortage).toContainText('200');
  await expect(shortage).toContainText('5%');
  await expect(shortage).toContainText('210');
  await main.keyboard.press('Escape');
  await expect(main.getByRole('button', { name: /run payment/i })).toHaveCount(
    0,
  );

  // Out of order Director actions fail with a message.
  await dir.reload();
  await director(dir, 'RELEASE_SURPLUS_CYCLE');
  await expect(dir.getByTestId('director-message')).toContainText('Load D+1');

  // Scene 6: execution; unknown is held until released.
  await director(dir, 'RELEASE_EXECUTION_WINDOW');
  await expect(dir.getByTestId('director-message')).toContainText(
    'RELEASE_EXECUTION_WINDOW',
  );
  await main.getByRole('tab', { name: 'Execution' }).click();
  await expect(main.getByTestId('execution-timeline')).toBeVisible();
  await expect(main.getByTestId('pay-outcome-unknown')).toHaveText(
    'Outcome unknown',
    {
      timeout: 60_000,
    },
  );
  await main.getByRole('button', { name: 'View transaction status' }).click();
  const tx = main.getByTestId('tx-status');
  await expect(tx).toContainText('SIM-TX-PAY-001');
  await expect(tx).toContainText('Verification pending');
  await expect(tx).toContainText('Refresh pending');
  await expect(main.getByRole('button', { name: /retry/i })).toHaveCount(0);
  await main.keyboard.press('Escape');
  await expect(main.getByTestId('invoice-status')).toHaveText(
    'Outcome unknown',
  );
  await expect(main.getByTestId('payment-count')).toHaveText('0');
  await expect(main.getByTestId('recon-status')).toHaveText(
    'Pending verification',
  );
  // Held: still unknown after a while.
  await main.waitForTimeout(4_000);
  await expect(main.getByTestId('pay-outcome-unknown')).toBeVisible();

  await director(dir, 'RELEASE_PAY_VERIFICATION');
  await expect(main.getByTestId('invoice-status')).toHaveText('Paid');
  await expect(main.getByTestId('payment-count')).toHaveText('1');
  await expect(main.getByTestId('recon-status')).toHaveText('Matching');
  await expect(main.getByTestId('recon-status')).toHaveText('Matched', {
    timeout: 15_000,
  });
  await expect(dir.getByTestId('director-stage')).toHaveText('S3');

  // Scene 7: evidence.
  await main.getByRole('tab', { name: 'Evidence' }).click();
  await main.getByRole('button', { name: 'View payment evidence' }).click();
  const evidence = main.getByTestId('payment-evidence');
  await expect(evidence).toContainText('SIM-TX-PAY-001');
  await expect(evidence).toContainText('Receipt checks');
  await expect(evidence).toContainText('SIMULATED');
  await expect(evidence).toContainText('Reconciliation');
  await expect(evidence).toContainText('Matched');
  await expect(evidence).toContainText('≈18.05');
  await expect(evidence.locator('a')).toHaveCount(0);
  await main.keyboard.press('Escape');

  // Scene 8: next day, allocation, supply plan, supply.
  await director(dir, 'LOAD_DAY_D_PLUS_ONE');
  await main.getByRole('link', { name: 'Liquidity' }).click();
  await expect(main.getByTestId('next-day-banner')).toContainText(
    'Scenario time advanced',
  );
  await expect(main.getByTestId('revenue-confirmed')).toContainText('2,000');
  await expect(main.getByTestId('obligation-c')).toContainText('700');
  await main.getByRole('button', { name: 'View allocation' }).click();
  await expect(main.getByTestId('allocation-equation')).toHaveText(
    '2,410 - 300 - 700 - 100 = 1,310',
  );
  await main.keyboard.press('Escape');
  await main.getByRole('button', { name: 'View supply plan' }).click();
  await expect(main.getByTestId('supply-plan')).toContainText('1,310');
  await expect(main.getByTestId('supply-plan')).toContainText('3,100 / 3,500');
  await main.keyboard.press('Escape');
  await director(dir, 'RELEASE_SURPLUS_CYCLE');
  await expect(main.getByTestId('supply-status')).toHaveText('Confirmed', {
    timeout: 30_000,
  });
  await expect(dir.getByTestId('director-stage')).toHaveText('S5');

  // Scene 9: security block, then pause as Minh.
  await director(dir, 'LOAD_SECURITY_INBOX');
  await switchRole(main, 'Linh');
  await main.getByRole('link', { name: 'Invoices' }).click();
  await main.getByRole('link', { name: 'INV-CLOUD-043' }).click();
  await expect(main.getByText('UNKNOWN_RECIPIENT').first()).toBeVisible();
  await main.getByTestId('submit-invoice').click();
  const block = main.getByTestId('security-block');
  await expect(block).toContainText('BLOCKED_UNKNOWN_RECIPIENT');
  await expect(block).toContainText('Approvals: 0');
  await main.getByRole('button', { name: 'View security evidence' }).click();
  await expect(main.getByTestId('security-report')).toContainText('App block');
  await expect(main.getByTestId('security-report')).toContainText(
    'Contract-negative test',
  );
  await expect(main.getByTestId('security-report-badge')).toHaveText(
    'Simulated',
  );
  await expect(main.getByText('SIM-TEST-AUTHORITY-001').first()).toBeVisible();
  await main.keyboard.press('Escape');
  await expect(dir.getByTestId('director-stage')).toHaveText('S5');

  await expect(main.getByRole('button', { name: 'Pause agent' })).toHaveCount(
    0,
  );
  await switchRole(main, 'Minh');
  await main.getByRole('link', { name: 'Controls' }).click();
  await main.getByRole('tab', { name: 'Agent controls' }).click();
  await expect(main.getByTestId('agent-status')).toHaveText('Active');
  await main.getByTestId('agent-pause').click();
  await main.getByRole('button', { name: 'Confirm pause' }).click();
  await expect(main.getByTestId('agent-status')).toHaveText('Pausing');
  await expect(main.getByTestId('agent-status')).toHaveText('Paused', {
    timeout: 15_000,
  });
  await expect(main.getByTestId('agent-activity')).toContainText(
    'Next agent cycle skipped: AGENT_PAUSED',
  );
  await expect(dir.getByTestId('director-stage')).toHaveText('S5');

  // Scenes 10 and 11: overlays from the Director, never controls in the main window.
  await director(dir, 'SHOW_AGENT_OVERLAY');
  await expect(main.getByTestId('overlay-agent')).toContainText(
    'How the agent works',
  );
  await director(dir, 'SHOW_OUTCOME_OVERLAY');
  const outcome = main.getByTestId('overlay-outcome');
  await expect(outcome).toContainText('Invoice A: paid 980 / matched');
  await expect(outcome).toContainText(
    'Payroll and upcoming bill reserves preserved',
  );
  await expect(outcome).toContainText(
    'One payment / unknown outcome verified before completion',
  );
  await expect(outcome).toContainText(
    'Only 1,310 surplus supplied / agent now paused',
  );
  await expect(main.getByText('No guaranteed yield.')).toBeVisible();
  await expect(main.getByText('Director panel')).toHaveCount(0);
  await director(dir, 'HIDE_OVERLAY');
  await expect(main.getByTestId('overlay-outcome')).toHaveCount(0);
});

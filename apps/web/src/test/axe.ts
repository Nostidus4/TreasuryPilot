import axe, { type AxeResults } from 'axe-core';

/**
 * Runs axe-core over `container` and returns the violations. jsdom has no
 * layout or paint, so colour-contrast and region checks are switched off;
 * they are covered by the design tokens and the manual contrast item in
 * docs/modules/web/wording-checklist.md.
 */
export async function axeViolations(
  container: Element = document.body,
): Promise<AxeResults['violations']> {
  const results = await axe.run(container, {
    rules: {
      'color-contrast': { enabled: false },
      region: { enabled: false },
    },
  });
  return results.violations;
}

/** The violations that fail the build: critical and serious only. */
export async function seriousViolations(
  container: Element = document.body,
): Promise<AxeResults['violations']> {
  return (await axeViolations(container)).filter(
    (violation) =>
      violation.impact === 'critical' || violation.impact === 'serious',
  );
}

export function describeViolations(
  violations: AxeResults['violations'],
): string {
  return violations
    .map(
      (violation) =>
        `${violation.impact}: ${violation.id} — ${violation.nodes
          .map((node) => node.target.join(' '))
          .join(', ')}`,
    )
    .join('\n');
}

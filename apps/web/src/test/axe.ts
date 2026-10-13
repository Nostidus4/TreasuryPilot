import axe, { type AxeResults } from 'axe-core';

/**
 * Runs axe-core over `container` and returns the violations. jsdom has no
 * layout or paint, so colour-contrast and region checks are switched off;
 * they are covered by the design tokens and the manual checklist.
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

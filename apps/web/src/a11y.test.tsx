import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test } from 'vitest';

import { describeViolations, seriousViolations } from '@/test/axe';
import { renderApp } from '@/test/render';

const BASE = '/o/org_northwind';
const T = `${BASE}/t/trs_main`;

// WEB-022 (#228): no critical axe violations on the three core flows.
const flows = [
  ['dashboard', T, 'Liquidity'],
  ['approve', `${BASE}/approvals/req_288`, 'Fields'],
  ['exceptions', `${BASE}/review`, 'Select an item'],
] as const;

for (const [name, path, ready] of flows) {
  test(`the ${name} flow has no critical or serious axe violations`, async () => {
    renderApp(path, { demoWallet: true });
    // Wait for content that only exists once the data has loaded.
    await screen.findAllByText(ready);
    await waitFor(() =>
      expect(document.querySelector('[aria-busy="true"]')).toBeNull(),
    );
    expect(describeViolations(await seriousViolations())).toBe('');
  });
}

test('the notification list passes axe', async () => {
  const user = userEvent.setup();
  renderApp(T);
  await user.click(
    await screen.findByRole('button', { name: /^notifications/i }),
  );
  await screen.findByText(/mark all read/i);
  expect(describeViolations(await seriousViolations())).toBe('');
});

/** Makes `matchMedia` answer as a 390 px wide phone. */
function usePhoneViewport() {
  // jsdom has no matchMedia; the app then falls back to the desktop layout.
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (query: string) => {
      const min = /min-width:\s*(\d+)px/.exec(query);
      return {
        matches: min ? 390 >= Number(min[1]) : false,
        media: query,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
      } as MediaQueryList;
    },
  });
  return () => {
    Reflect.deleteProperty(window, 'matchMedia');
  };
}

test('at 390 px the notifications open as a named bottom sheet that passes axe', async () => {
  const restore = usePhoneViewport();
  try {
    const user = userEvent.setup();
    renderApp(T);
    await user.click(
      await screen.findByRole('button', { name: /^notifications/i }),
    );
    expect(
      await screen.findByRole('dialog', { name: 'Notifications' }),
    ).toBeInTheDocument();
    expect(describeViolations(await seriousViolations())).toBe('');
  } finally {
    restore();
  }
});

test('at 390 px the approval screen shows one pane with a way back to the list', async () => {
  const restore = usePhoneViewport();
  try {
    renderApp(`${BASE}/approvals/req_288`, { demoWallet: true });
    expect(
      await screen.findByRole('button', { name: /open navigation/i }),
    ).toBeInTheDocument();
    await screen.findAllByRole('heading', { level: 1 });
    expect(
      await screen.findByRole('link', { name: /back to the list/i }),
    ).toHaveAttribute('href', `${BASE}/approvals`);
    expect(describeViolations(await seriousViolations())).toBe('');
  } finally {
    restore();
  }
});

test('keyboard: the skip link is the first stop and jumps to the main region', async () => {
  const user = userEvent.setup();
  renderApp(T);
  await screen.findByRole('heading', { name: 'Liquidity' });
  await user.tab();
  const skip = screen.getByRole('link', { name: /skip to content/i });
  expect(skip).toHaveFocus();
  await user.keyboard('{Enter}');
  expect(window.location.hash).toBe('#main');
});

test('keyboard: the notification popover opens with Enter and closes with Escape, returning focus', async () => {
  const user = userEvent.setup();
  renderApp(T);
  const bell = await screen.findByRole('button', { name: /^notifications/i });
  bell.focus();
  await user.keyboard('{Enter}');
  expect(
    await screen.findByRole('dialog', { name: 'Notifications' }),
  ).toBeInTheDocument();
  await user.keyboard('{Escape}');
  await waitFor(() =>
    expect(
      screen.queryByRole('dialog', { name: 'Notifications' }),
    ).not.toBeInTheDocument(),
  );
  expect(bell).toHaveFocus();
});

test('keyboard: Ctrl+K opens the command menu and Escape closes it', async () => {
  const user = userEvent.setup();
  renderApp(T);
  await screen.findByRole('heading', { name: 'Liquidity' });
  await user.keyboard('{Control>}k{/Control}');
  expect(
    await screen.findByRole('dialog', { name: 'Command menu' }),
  ).toBeInTheDocument();
  await user.keyboard('{Escape}');
  await waitFor(() =>
    expect(
      screen.queryByRole('dialog', { name: 'Command menu' }),
    ).not.toBeInTheDocument(),
  );
});

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, test } from 'vitest';

import { App } from '@/app';
import { AuthProvider } from '@/features/auth/auth-context';

function renderApp(initialPath: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

test('renders the public login shell', () => {
  renderApp('/login');

  expect(
    screen.getByRole('heading', { name: /human approval/i }),
  ).toBeInTheDocument();
});

test('redirects an unauthenticated user to login', async () => {
  renderApp('/');

  expect(
    await screen.findByRole('button', { name: /preview application shell/i }),
  ).toBeInTheDocument();
});

test('opens the interactive dashboard from the preview entry', async () => {
  renderApp('/login');

  fireEvent.click(
    screen.getByRole('button', { name: /preview application shell/i }),
  );

  expect(
    await screen.findByRole('heading', { name: /good morning, avery/i }),
  ).toBeInTheDocument();
});

test('restores a protected deep link after starting the preview session', async () => {
  renderApp('/mock/plans');

  fireEvent.click(
    await screen.findByRole('button', { name: /preview application shell/i }),
  );

  expect(
    await screen.findByRole('heading', { name: /ai payment plan/i }),
  ).toBeInTheDocument();
});

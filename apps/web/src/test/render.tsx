import { QueryClient } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { App } from '@/app';
import { resetDb } from '@/mocks/db';
import { AppProviders } from '@/providers/app-providers';

/** Renders the whole app against the mock API at `path`. */
export function renderApp(
  path: string,
  options: { signedIn?: boolean; demoWallet?: boolean } = {},
) {
  resetDb({ timeScale: 0, signedIn: options.signedIn ?? true });
  if (options.demoWallet) {
    window.sessionStorage.setItem('treasurypilot.demo-wallet', 'on');
  }
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppProviders client={client}>
        <App />
      </AppProviders>
    </MemoryRouter>,
  );
}

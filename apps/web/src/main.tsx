import '@fontsource-variable/ibm-plex-sans';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import { App } from '@/app';
import { mockApiEnabled } from '@/lib/env';
import '@/lib/i18n';
import { initTheme } from '@/lib/theme';
import { AppProviders } from '@/providers/app-providers';
import '@/styles.css';

async function start() {
  initTheme();
  if (import.meta.env.VITE_SENTRY_DSN) {
    // Loaded only when configured, so builds without a DSN ship no Sentry code.
    const Sentry = await import('@sentry/react');
    Sentry.init({ dsn: import.meta.env.VITE_SENTRY_DSN, environment: import.meta.env.MODE });
  }
  if (mockApiEnabled) {
    const { startMockApi } = await import('@/mocks/browser');
    await startMockApi();
  }
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <BrowserRouter basename={import.meta.env.BASE_URL}>
        <AppProviders>
          <App />
        </AppProviders>
      </BrowserRouter>
    </React.StrictMode>,
  );
}

void start();

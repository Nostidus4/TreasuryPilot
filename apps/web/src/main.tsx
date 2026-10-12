import '@fontsource-variable/geist';
import '@fontsource-variable/geist-mono';
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

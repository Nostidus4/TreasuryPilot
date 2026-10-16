import path from 'node:path';
import { fileURLToPath } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const rootDirectory = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  base: process.env.VITE_BASE_PATH ?? '/',
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(rootDirectory, 'src'),
    },
  },
  server: {
    port: 5173,
    // Full-stack E2E (playwright.stack.config.ts): same-origin /api so session cookies work.
    proxy: process.env.E2E_API_PROXY_TARGET
      ? {
          '/api': {
            target: process.env.E2E_API_PROXY_TARGET,
            rewrite: (requestPath) => requestPath.replace(/^\/api/, ''),
          },
        }
      : undefined,
  },
});

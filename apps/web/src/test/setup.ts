import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest';

import '@/lib/i18n';
import { resetDb } from '@/mocks/db';
import { server } from '@/mocks/server';

class ResizeObserverMock implements ResizeObserver {
  disconnect() {}
  observe() {}
  unobserve() {}
}

globalThis.ResizeObserver = ResizeObserverMock;
// Radix and cmdk call these; jsdom does not implement them.
Element.prototype.scrollIntoView = () => {};
Element.prototype.hasPointerCapture = () => false;
Element.prototype.releasePointerCapture = () => {};

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
beforeEach(() => resetDb({ timeScale: 0 }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  window.sessionStorage.clear();
  // Node 25+ ships its own localStorage global, which can shadow jsdom's.
  window.localStorage?.clear?.();
});
afterAll(() => server.close());

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import type { PropsWithChildren } from 'react';
import { afterEach, expect, test, vi } from 'vitest';

import { useLiveEvents } from '@/lib/live-events';

class TestEventSource extends EventTarget {
  static current: TestEventSource | undefined;

  constructor() {
    super();
    TestEventSource.current = this;
  }

  close() {}
}

afterEach(() => {
  TestEventSource.current = undefined;
  vi.unstubAllGlobals();
});

test('a named operation.status event invalidates the organization plan query', () => {
  vi.stubGlobal('EventSource', TestEventSource);
  const queryClient = new QueryClient();
  const invalidateQueries = vi.spyOn(queryClient, 'invalidateQueries');
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  const { unmount } = renderHook(() => useLiveEvents('org_123'), { wrapper });
  act(() => {
    TestEventSource.current?.dispatchEvent(
      new MessageEvent('operation.status', {
        data: JSON.stringify({
          eventId: 'event-1',
          eventType: 'OperationUpdated',
          entityType: 'operation',
          entityId: 'operation-1',
        }),
      }),
    );
  });

  expect(invalidateQueries).toHaveBeenCalledWith({
    queryKey: ['org', 'org_123', 'plans'],
  });
  unmount();
  queryClient.clear();
});

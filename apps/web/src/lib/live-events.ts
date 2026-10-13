import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { apiUrl } from '@/lib/api/http';
import type { ServerEvent } from '@/lib/api/types';
import { isTest } from '@/lib/env';

/** Which cached entities each event type makes stale (M16-D7). */
const affected: Record<ServerEvent['type'], string[]> = {
  plan: ['plans', 'treasury', 'requests', 'reconciliations', 'review'],
  operation: ['plans', 'treasury'],
  request: ['requests', 'treasury'],
  governance: ['governance', 'treasury', 'mandates', 'payees', 'review'],
  notification: ['notifications', 'treasury'],
};

const POLL_MS = isTest ? 150 : 10_000;

/**
 * Subscribes to the org event stream and invalidates the matching queries.
 * EventSource reconnects by itself and resends Last-Event-ID; while the
 * stream is down (or unsupported) the same queries are polled every 10 s.
 */
export function useLiveEvents(orgId: string | undefined): { live: boolean } {
  const queryClient = useQueryClient();
  const [live, setLive] = useState(false);

  useEffect(() => {
    if (!orgId || typeof EventSource === 'undefined') return;
    const source = new EventSource(apiUrl(`/orgs/${orgId}/events`), {
      withCredentials: true,
    });
    source.onopen = () => setLive(true);
    source.onerror = () => setLive(false);
    source.onmessage = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as ServerEvent;
      for (const entity of affected[event.type] ?? []) {
        void queryClient.invalidateQueries({
          queryKey: ['org', orgId, entity],
        });
      }
    };
    return () => {
      source.close();
      setLive(false);
    };
  }, [orgId, queryClient]);

  useEffect(() => {
    if (!orgId || live) return;
    const timer = window.setInterval(() => {
      void queryClient.invalidateQueries({ queryKey: ['org', orgId] });
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [live, orgId, queryClient]);

  return { live };
}

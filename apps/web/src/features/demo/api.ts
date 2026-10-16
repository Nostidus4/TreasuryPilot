import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query';
import { useEffect } from 'react';

import { api, errorMessage } from '@/lib/api/http';

import type { DemoRole, ScenarioView } from './types';

export const demoKey = ['demo', 'scenario'] as const;

/** Raised by the scenario store whenever its state changes (either window). */
const CHANGED_EVENT = 'treasurypilot:demo-changed';

function refreshAll(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: demoKey });
  void queryClient.invalidateQueries({ queryKey: ['me'] });
  void queryClient.invalidateQueries({ queryKey: ['org'] });
}

/** Keeps every query in step with the scenario, including changes made by the Director window. */
export function useDemoSync() {
  const queryClient = useQueryClient();
  useEffect(() => {
    const onChange = () => refreshAll(queryClient);
    window.addEventListener(CHANGED_EVENT, onChange);
    return () => window.removeEventListener(CHANGED_EVENT, onChange);
  }, [queryClient]);
}

export function useScenario() {
  return useQuery({
    queryKey: demoKey,
    queryFn: ({ signal }) =>
      api.get<ScenarioView>('/demo/scenario', { signal }),
    staleTime: 0,
  });
}

/** A scenario action. The server answers with the new view; failures carry a readable message. */
export function useDemoAction<Input = void>(
  path: string | ((input: Input) => string),
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: Input) =>
      api.post<ScenarioView & { noop: boolean; message: string | null }>(
        typeof path === 'function' ? path(input) : path,
        input && typeof input === 'object' ? input : {},
      ),
    onSettled: () => refreshAll(queryClient),
  });
}

export function useSwitchRole() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (role: DemoRole) => api.post('/demo/role', { role }),
    onSuccess: () => {
      // A role switch changes who is signed in; it never resets the scenario.
      void queryClient.invalidateQueries();
    },
  });
}

export const actionError = errorMessage;

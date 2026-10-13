import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from '@tanstack/react-query';

import { api } from '@/lib/api/http';

/**
 * Query keys are `['org', orgId, entity, ...rest]`. Live events and mutations
 * invalidate by that prefix, so a hook only has to name its entity.
 */
export function useOrgQuery<T>(
  orgId: string,
  entity: string,
  rest: ReadonlyArray<string | undefined>,
  path: string,
  options?: Omit<UseQueryOptions<T>, 'queryKey' | 'queryFn'> & {
    query?: Record<string, string | undefined>;
  },
) {
  const { query, ...queryOptions } = options ?? {};
  return useQuery<T>({
    queryKey: ['org', orgId, entity, ...rest, query ?? null],
    queryFn: ({ signal }) =>
      api.get<T>(`/orgs/${orgId}${path}`, { query, signal }),
    ...queryOptions,
  });
}

/** A mutation that refreshes everything cached for the org when it succeeds. */
export function useOrgMutation<Input, Output>(
  orgId: string,
  mutationFn: (input: Input) => Promise<Output>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['org', orgId] }),
  });
}

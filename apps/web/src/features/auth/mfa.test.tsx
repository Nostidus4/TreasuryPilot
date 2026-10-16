import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { StepUpDialog } from '@/features/auth/mfa';

afterEach(() => vi.restoreAllMocks());

test('the step-up dialog posts the code, then continues', async () => {
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValue(new Response(null, { status: 204 }));
  const onDone = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <StepUpDialog open onOpenChange={() => undefined} onDone={onDone} />
    </QueryClientProvider>,
  );

  fireEvent.change(screen.getByLabelText('Authenticator code'), {
    target: { value: '123456' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));

  await waitFor(() => expect(onDone).toHaveBeenCalledOnce());
  const [url, init] = fetchMock.mock.calls[0];
  expect(url as string).toContain('/v1/me/mfa/step-up');
  expect(JSON.parse((init as RequestInit).body as string)).toEqual({
    code: '123456',
  });
});

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type PropsWithChildren, useState } from 'react';
import { Toaster } from 'sonner';
import { WagmiProvider } from 'wagmi';

import { TooltipProvider } from '@/components/ui/menus';
import { isApiError } from '@/lib/api/http';
import { wagmiConfig } from '@/lib/wallet/config';
import { WalletProvider } from '@/lib/wallet/wallet-context';

export function AppProviders({
  children,
  client,
}: PropsWithChildren<{ client?: QueryClient }>) {
  const [queryClient] = useState(
    () =>
      client ??
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            // A 4xx will not fix itself: retry only network and 5xx failures.
            retry: (count, error) =>
              count < 2 &&
              !(isApiError(error) && error.status >= 400 && error.status < 500),
          },
        },
      }),
  );

  return (
    <WagmiProvider config={wagmiConfig}>
      <QueryClientProvider client={queryClient}>
        <WalletProvider>
          <TooltipProvider delayDuration={300}>
            {children}
            <Toaster
              position="bottom-right"
              toastOptions={{
                classNames: {
                  toast:
                    'rounded-lg border border-border bg-surface text-foreground shadow-float font-sans text-base',
                  description: 'text-muted-foreground text-sm',
                },
              }}
            />
          </TooltipProvider>
        </WalletProvider>
      </QueryClientProvider>
    </WagmiProvider>
  );
}

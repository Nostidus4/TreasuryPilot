import { type PropsWithChildren, useCallback, useMemo, useState } from 'react';

import { AuthContext, type Session } from '@/features/auth/auth-context-value';

const previewKey = 'treasurypilot.preview-session';

export function AuthProvider({ children }: PropsWithChildren) {
  const [session, setSession] = useState<Session | null>(() =>
    window.sessionStorage.getItem(previewKey) ? { userId: 'preview' } : null,
  );
  const startPreviewSession = useCallback(() => {
    window.sessionStorage.setItem(previewKey, 'true');
    setSession({ userId: 'preview' });
  }, []);
  const signOut = useCallback(() => {
    window.sessionStorage.removeItem(previewKey);
    setSession(null);
  }, []);
  const value = useMemo(
    () => ({ session, signOut, startPreviewSession }),
    [session, signOut, startPreviewSession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

import { useContext } from 'react';

import {
  AuthContext,
  type AuthContextValue,
} from '@/features/auth/auth-context-value';

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used inside AuthProvider');
  }
  return context;
}

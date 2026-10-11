import { createContext } from 'react';

export type Session = { userId: string };

export type AuthContextValue = {
  session: Session | null;
  startPreviewSession: () => void;
  signOut: () => void;
};

export const AuthContext = createContext<AuthContextValue | null>(null);

'use client';

import { createContext, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';

import {
  AuthSession,
  LoginPayload,
  getStoredSession,
  loginWithGeneratedClient,
  removeStoredSession,
  setStoredSession,
} from '@/lib/auth';

interface AuthContextValue {
  isHydrating: boolean;
  isSignedIn: boolean;
  login: (payload: LoginPayload) => Promise<AuthSession>;
  logout: () => void;
  session: AuthSession | null;
}

const AuthContext = createContext<AuthContextValue | null>(null);

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps): JSX.Element {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [isHydrating, setIsHydrating] = useState(true);

  useEffect(() => {
    setSession(getStoredSession());
    setIsHydrating(false);
  }, []);

  const login = async (payload: LoginPayload): Promise<AuthSession> => {
    const nextSession = await loginWithGeneratedClient(payload);
    setStoredSession(nextSession);
    setSession(nextSession);
    return nextSession;
  };

  const logout = (): void => {
    removeStoredSession();
    setSession(null);
  };

  return (
    <AuthContext.Provider
      value={{
        isHydrating,
        isSignedIn: Boolean(session),
        login,
        logout,
        session,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);

  if (!context) {
    throw new Error('AuthProvider is required for auth state.');
  }

  return context;
}

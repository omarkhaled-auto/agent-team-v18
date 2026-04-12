'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { auth as authApi, ApiRequestError } from '@project/api-client';
import type { User } from '@project/api-client';
import { apiOptions, getStoredToken, setStoredToken, clearStoredToken } from './api';

type SafeUser = Omit<User, 'ownedProjects' | 'assignedTasks' | 'reportedTasks' | 'comments'>;

interface AuthState {
  user: SafeUser | null;
  token: string | null;
  isLoading: boolean;
  isAuthenticated: boolean;
}

interface AuthActions {
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, name: string, password: string) => Promise<void>;
  logout: () => void;
}

type AuthContextValue = AuthState & AuthActions;

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SafeUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Hydrate from stored token on mount
  useEffect(() => {
    const controller = new AbortController();
    const stored = getStoredToken();
    if (!stored) {
      setIsLoading(false);
      return;
    }

    setToken(stored);
    authApi
      .me({
        ...apiOptions(stored),
        init: { ...apiOptions(stored).init, signal: controller.signal },
      })
      .then((res) => {
        setUser(res.data);
      })
      .catch(() => {
        clearStoredToken();
        setToken(null);
      })
      .finally(() => {
        setIsLoading(false);
      });

    return () => controller.abort();
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await authApi.login({ body: { email, password } }, apiOptions());
    const accessToken = res.data.access_token;
    setStoredToken(accessToken);
    setToken(accessToken);
    setUser(res.data.user);
  }, []);

  const register = useCallback(async (email: string, name: string, password: string) => {
    const res = await authApi.register({ body: { email, name, password } }, apiOptions());
    const accessToken = res.data.token;
    setStoredToken(accessToken);
    setToken(accessToken);
    setUser(res.data.user);
  }, []);

  const logout = useCallback(() => {
    clearStoredToken();
    setToken(null);
    setUser(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      isLoading,
      isAuthenticated: !!user && !!token,
      login,
      register,
      logout,
    }),
    [user, token, isLoading, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
}

export type AuthRole = 'ADMIN' | 'MEMBER';

export interface AuthUser {
  avatar_url?: string | null;
  created_at?: string;
  email: string;
  id: string;
  name: string;
  role: AuthRole;
  updated_at?: string;
}

export interface AuthSession {
  accessToken: string;
  user: AuthUser;
}

export interface LoginPayload {
  email: string;
  password: string;
}

const authStorageKey = 'signal-desk.session';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isAuthRole(value: unknown): value is AuthRole {
  return value === 'ADMIN' || value === 'MEMBER';
}

function isAuthUser(value: unknown): value is AuthUser {
  if (!isRecord(value)) {
    return false;
  }

  return (
    typeof value.id === 'string' &&
    typeof value.email === 'string' &&
    typeof value.name === 'string' &&
    isAuthRole(value.role) &&
    (value.avatar_url === undefined || value.avatar_url === null || typeof value.avatar_url === 'string') &&
    (value.created_at === undefined || typeof value.created_at === 'string') &&
    (value.updated_at === undefined || typeof value.updated_at === 'string')
  );
}

function isAuthSession(value: unknown): value is AuthSession {
  return isRecord(value) && typeof value.accessToken === 'string' && isAuthUser(value.user);
}

export class AuthClientUnavailableError extends Error {
  constructor() {
    super(
      'Generated API client import failed because Wave C emitted duplicate export names and incorrect auth types.',
    );
    this.name = 'AuthClientUnavailableError';
  }
}

export function getStoredSession(): AuthSession | null {
  if (typeof window === 'undefined') {
    return null;
  }

  const raw = window.localStorage.getItem(authStorageKey);

  if (!raw) {
    return null;
  }

  try {
    const parsed: unknown = JSON.parse(raw);
    return isAuthSession(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function setStoredSession(session: AuthSession): void {
  if (typeof window === 'undefined') {
    return;
  }

  window.localStorage.setItem(authStorageKey, JSON.stringify(session));
}

export function removeStoredSession(): void {
  if (typeof window === 'undefined') {
    return;
  }

  window.localStorage.removeItem(authStorageKey);
}

export async function loginWithGeneratedClient(_payload: LoginPayload): Promise<AuthSession> {
  throw new AuthClientUnavailableError();
}

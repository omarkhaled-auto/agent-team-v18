import type { RequestOptions } from '@project/api-client';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080/api';

/**
 * Build RequestOptions with the API base URL and optional JWT auth header.
 * Call this in every API call to ensure consistent configuration.
 */
export function apiOptions(token?: string | null): RequestOptions {
  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  return {
    baseUrl: API_BASE_URL,
    init: {
      headers,
      credentials: 'include' as RequestCredentials,
    },
  };
}

/**
 * Token storage keys
 */
const TOKEN_KEY = 'taskflow_token';

export function getStoredToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(TOKEN_KEY);
}

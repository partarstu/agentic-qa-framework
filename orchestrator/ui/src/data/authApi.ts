// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { ApiError, clearSession, request, storedSession, storeSession } from './client';

interface TokenResponse {
  access_token: string;
  expires_at: string;
}

export type LoginResult =
  | { kind: 'ok'; username: string }
  | { kind: 'rejected' }
  | { kind: 'rate-limited'; retryAfterSeconds: number | null }
  | { kind: 'failed' };

export async function login(username: string, password: string): Promise<LoginResult> {
  try {
    const token = await request<TokenResponse>('/api/auth/login', { method: 'POST', body: { username, password }, authenticated: false });
    storeSession(token.access_token, token.expires_at, username);
    return { kind: 'ok', username };
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return { kind: 'rejected' };
    }
    if (error instanceof ApiError && error.status === 429) {
      return { kind: 'rate-limited', retryAfterSeconds: error.retryAfterSeconds };
    }
    return { kind: 'failed' };
  }
}

export type SessionProbe = { kind: 'active'; username: string } | { kind: 'none' } | { kind: 'unreachable' };

/** Whether the stored session still holds: a rejected token leads to the login, an orchestrator that does not answer to a retry. */
export async function probeSession(): Promise<SessionProbe> {
  const session = storedSession();
  if (session === null) {
    clearSession();
    return { kind: 'none' };
  }
  try {
    const { username } = await request<{ username: string }>('/api/auth/verify');
    return { kind: 'active', username };
  } catch (error) {
    return error instanceof ApiError && error.status === 401 ? { kind: 'none' } : { kind: 'unreachable' };
  }
}

/** Ends the session in this browser; the orchestrator keeps no session to end, so its answer does not matter. */
export function logout(): void {
  clearSession();
  void request('/api/auth/logout', { method: 'POST', authenticated: false }).catch(() => undefined);
}

// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { request, storedSession } from './client';

const RENEW_BEFORE_EXPIRY_MS = 30_000;

let cached: { token: string; expiresAt: number; sessionToken: string | undefined } | null = null;

/** A stream token for the SSE URLs, which cannot carry the bearer header; a new one once the cached one is about to expire or the session changed. */
export async function getStreamToken(): Promise<string> {
  const sessionToken = storedSession()?.token;
  if (cached && cached.sessionToken === sessionToken && cached.expiresAt - Date.now() > RENEW_BEFORE_EXPIRY_MS) {
    return cached.token;
  }
  const response = await request<{ stream_token: string; expires_at: string }>('/api/dashboard/stream-token', { method: 'POST' });
  cached = { token: response.stream_token, expiresAt: new Date(response.expires_at).getTime(), sessionToken };
  return cached.token;
}

export function clearStreamToken(): void {
  cached = null;
}

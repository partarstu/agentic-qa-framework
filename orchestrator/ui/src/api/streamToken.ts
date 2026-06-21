import { apiClient } from './client';

interface StreamTokenResponse {
  stream_token: string;
  expires_at: string;
}

let _cached: { token: string; expiresAt: number } | null = null;

/**
 * Returns a valid stream token, fetching a fresh one via POST /stream-token when
 * the cached token is absent or within 30 s of expiry.
 */
export async function getStreamToken(): Promise<string> {
  const now = Date.now();
  if (_cached && _cached.expiresAt - now > 30_000) {
    return _cached.token;
  }
  const response = await apiClient.post<StreamTokenResponse>('/stream-token');
  _cached = {
    token: response.data.stream_token,
    expiresAt: new Date(response.data.expires_at).getTime(),
  };
  return _cached.token;
}

/** Clears the cached token, forcing a fresh fetch on the next call. */
export function clearStreamToken(): void {
  _cached = null;
}

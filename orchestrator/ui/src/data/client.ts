// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { useSyncExternalStore } from 'react';

export const DEFAULT_TIMEOUT_MS = 5_000;
export const LOG_TIMEOUT_MS = 30_000;
// Above the orchestrator's agent discovery timeout (AGENT_DISCOVERY_TIMEOUT_SECONDS, 120 s)
export const DISCOVERY_TIMEOUT_MS = 130_000;

const TOKEN_KEY = 'dashboard_auth_token';
const EXPIRES_KEY = 'dashboard_auth_expires';
const USERNAME_KEY = 'dashboard_auth_username';
const GATEWAY_STATUSES = new Set([502, 503, 504]);

/** A request the orchestrator answered with an error status; `retryAfterSeconds` comes from a 429's `Retry-After`. */
export class ApiError extends Error {
  constructor(readonly status: number, message: string, readonly retryAfterSeconds: number | null = null) {
    super(message);
  }
}

export class RequestTimeoutError extends Error {}

export interface Session {
  token: string;
  username: string;
}

export function storedSession(): Session | null {
  const token = localStorage.getItem(TOKEN_KEY);
  const expiresAt = localStorage.getItem(EXPIRES_KEY);
  if (!token || !expiresAt || new Date(expiresAt) <= new Date()) {
    return null;
  }
  return { token, username: localStorage.getItem(USERNAME_KEY) ?? '' };
}

export function storeSession(token: string, expiresAt: string, username: string): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(EXPIRES_KEY, expiresAt);
  localStorage.setItem(USERNAME_KEY, username);
}

export function clearSession(): void {
  [TOKEN_KEY, EXPIRES_KEY, USERNAME_KEY].forEach((key) => localStorage.removeItem(key));
}

const expiryListeners = new Set<() => void>();

/** Calls the listener when a request finds the session rejected (401), after the stored session is cleared. */
export function onSessionExpired(listener: () => void): () => void {
  expiryListeners.add(listener);
  return () => expiryListeners.delete(listener);
}

const reachabilityListeners = new Set<() => void>();
let reachable = true;

function setReachable(next: boolean) {
  if (next !== reachable) {
    reachable = next;
    reachabilityListeners.forEach((listener) => listener());
  }
}

/** False after a network error, a timeout under the default timeout or a gateway status (502-504), until a request is answered. */
export function useOrchestratorReachable(): boolean {
  return useSyncExternalStore((listener) => {
    reachabilityListeners.add(listener);
    return () => reachabilityListeners.delete(listener);
  }, () => reachable);
}

interface RequestOptions {
  method?: 'GET' | 'POST';
  body?: unknown;
  query?: Record<string, string | number | null | undefined>;
  signal?: AbortSignal;
  timeoutMs?: number;
  /** False for the login, whose 401 is a wrong password rather than an expired session. */
  authenticated?: boolean;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query = {}, signal, timeoutMs = DEFAULT_TIMEOUT_MS, authenticated = true } = options;
  const params = new URLSearchParams(Object.entries(query).filter(([, value]) => value != null).map(([key, value]) => [key, String(value)]));
  const url = params.size > 0 ? `${path}?${params}` : path;
  const headers: Record<string, string> = {};
  const token = authenticated ? localStorage.getItem(TOKEN_KEY) : null;
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }
  const timeout = AbortSignal.timeout(timeoutMs);
  let response: Response;
  try {
    response = await fetch(url, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    });
  } catch (error) {
    // A request the caller cancelled says nothing about the orchestrator, and a long request may only be slow
    if (signal?.aborted) {
      throw error;
    }
    if (timeout.aborted) {
      if (timeoutMs === DEFAULT_TIMEOUT_MS) {
        setReachable(false);
      }
      throw new RequestTimeoutError(`${path} took longer than ${timeoutMs / 1_000} s`);
    }
    setReachable(false);
    throw error;
  }
  setReachable(!GATEWAY_STATUSES.has(response.status));
  if (response.status === 401 && authenticated) {
    clearSession();
    expiryListeners.forEach((listener) => listener());
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorDetail(response), retryAfterSeconds(response));
  }
  return (await response.json()) as T;
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const detail = ((await response.json()) as { detail?: unknown }).detail;
    return typeof detail === 'string' && detail ? detail : `${response.status} ${response.statusText}`;
  } catch {
    return `${response.status} ${response.statusText}`;
  }
}

function retryAfterSeconds(response: Response): number | null {
  const seconds = Number(response.headers.get('Retry-After'));
  return response.headers.has('Retry-After') && Number.isFinite(seconds) ? seconds : null;
}

// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDom } from '../testing/dom';
import { json, stubRoutes } from '../testing/network';
import { login } from './authApi';
import {
  ApiError, DEFAULT_TIMEOUT_MS, DISCOVERY_TIMEOUT_MS, LOG_TIMEOUT_MS, onSessionExpired, request, RequestTimeoutError, storedSession,
  storeSession, useOrchestratorReachable,
} from './client';
import { getLogPage, getSummary, triggerDiscovery } from './dashboardApi';

installDom();

const FUTURE = new Date(Date.now() + 3_600_000).toISOString();

/** Makes every request time out at once, recording the timeouts asked for. */
function timeOutRequests() {
  const timeouts: number[] = [];
  vi.spyOn(AbortSignal, 'timeout').mockImplementation((millis) => {
    timeouts.push(millis);
    return AbortSignal.abort(new DOMException('The operation timed out.', 'TimeoutError'));
  });
  vi.stubGlobal('fetch', vi.fn(async (_input: string, init: RequestInit) => {
    throw init.signal?.reason;
  }));
  return timeouts;
}

function reachability() {
  return renderHook(() => useOrchestratorReachable()).result;
}

/** Makes the orchestrator reachable again for the next test, since the state is the module's. */
async function answerOnce() {
  stubRoutes(() => ({}));
  await request('/api/dashboard/summary');
}

describe('request', () => {
  beforeEach(async () => {
    await answerOnce();
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('sends the stored token as a bearer header', async () => {
    storeSession('token-1', FUTURE, 'ops');
    const { calls } = stubRoutes(() => ({ tasks_total: 1 }));

    await getSummary();

    expect(new Headers(calls[0].init.headers).get('Authorization')).toBe('Bearer token-1');
  });

  it('logs out on a 401: the session is cleared and the listeners hear of it', async () => {
    storeSession('token-1', FUTURE, 'ops');
    const expired = vi.fn();
    const stop = onSessionExpired(expired);
    stubRoutes(() => json({ detail: 'Token expired' }, { status: 401 }));

    await expect(getSummary()).rejects.toMatchObject({ status: 401, message: 'Token expired' });

    expect(storedSession()).toBeNull();
    expect(expired).toHaveBeenCalledOnce();
    stop();
  });

  it('does not log out on the wrong password of a login', async () => {
    const expired = vi.fn();
    const stop = onSessionExpired(expired);
    stubRoutes(() => json({ detail: 'Invalid username or password' }, { status: 401 }));

    expect(await login('ops', 'wrong')).toEqual({ kind: 'rejected' });

    expect(expired).not.toHaveBeenCalled();
    stop();
  });

  it.each([
    ['a default request', () => getSummary(), DEFAULT_TIMEOUT_MS],
    ['a log request', () => getLogPage({ source: { kind: 'orchestrator' }, level: null, offset: 0, limit: 100 }), LOG_TIMEOUT_MS],
    ['the discovery', () => triggerDiscovery(), DISCOVERY_TIMEOUT_MS],
  ])('gives %s its timeout', async (_name, call, millis) => {
    const timeouts = timeOutRequests();

    await expect(call()).rejects.toBeInstanceOf(RequestTimeoutError);

    expect(timeouts).toEqual([millis]);
  });

  it.each([
    ['a network error', () => vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }))],
    ['a timeout under the default timeout', () => timeOutRequests()],
    ['a 502', () => stubRoutes(() => json({}, { status: 502 }))],
    ['a 503', () => stubRoutes(() => json({}, { status: 503 }))],
    ['a 504', () => stubRoutes(() => json({}, { status: 504 }))],
  ])('marks the orchestrator unreachable on %s, until a request is answered', async (_name, stub) => {
    const reachable = reachability();
    stub();

    await expect(getSummary()).rejects.toBeDefined();
    expect(reachable.current).toBe(false);

    await answerOnce();
    expect(reachable.current).toBe(true);
  });

  it.each([
    ['a 500, which the orchestrator answered', async () => {
      stubRoutes(() => json({ detail: 'boom' }, { status: 500 }));
      await expect(getSummary()).rejects.toBeInstanceOf(ApiError);
    }],
    ['a timed-out log request, which may only be slow', async () => {
      timeOutRequests();
      await expect(getLogPage({ source: { kind: 'agent', agentId: 'ui' }, level: null, offset: 0, limit: 100 })).rejects.toBeInstanceOf(RequestTimeoutError);
    }],
    ['a cancelled request', async () => {
      vi.stubGlobal('fetch', vi.fn(async (_input: string, init: RequestInit) => {
        throw init.signal?.reason;
      }));
      const controller = new AbortController();
      controller.abort();
      await expect(getSummary(controller.signal)).rejects.toBeDefined();
    }],
  ])('keeps the orchestrator reachable on %s', async (_name, fail) => {
    const reachable = reachability();

    await fail();

    expect(reachable.current).toBe(true);
  });
});

describe('login', () => {
  beforeEach(() => localStorage.clear());

  it('stores the session it gets', async () => {
    stubRoutes(() => ({ access_token: 'token-2', token_type: 'bearer', expires_at: FUTURE }));

    expect(await login('ops', 'secret')).toEqual({ kind: 'ok', username: 'ops' });

    expect(storedSession()).toEqual({ token: 'token-2', username: 'ops' });
  });

  it('reads the wait of a 429 from Retry-After', async () => {
    stubRoutes(() => json({ detail: 'Too many login attempts.' }, { status: 429, headers: { 'Retry-After': '42' } }));

    expect(await login('ops', 'secret')).toEqual({ kind: 'rate-limited', retryAfterSeconds: 42 });
  });

  it('fails without a wait when a 429 names none', async () => {
    stubRoutes(() => json({}, { status: 429 }));

    expect(await login('ops', 'secret')).toEqual({ kind: 'rate-limited', retryAfterSeconds: null });
  });

  it('fails when the orchestrator does not answer', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }));

    expect(await login('ops', 'secret')).toEqual({ kind: 'failed' });
  });
});

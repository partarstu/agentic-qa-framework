// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { vi } from 'vitest';

export interface FetchCall {
  path: string;
  params: URLSearchParams;
  init: RequestInit;
}

/** Answers every fetch with the route's response for the request; a route returning a plain value answers it as JSON with status 200. */
export function stubRoutes(route: (call: FetchCall) => Response | unknown | Promise<Response | unknown>) {
  const calls: FetchCall[] = [];
  const fetch = vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = new URL(input, 'http://dashboard');
    const call = { path: url.pathname, params: url.searchParams, init };
    calls.push(call);
    const answer = await route(call);
    return answer instanceof Response ? answer : json(answer);
  });
  vi.stubGlobal('fetch', fetch);
  return { calls, count: (path: string) => calls.filter((call) => call.path === path).length };
}

export function json(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body ?? null), { ...init, headers: { 'Content-Type': 'application/json', ...init.headers } });
}

export const STREAM_TOKEN_PATH = '/api/dashboard/stream-token';

export function streamToken(token: string) {
  return { stream_token: token, expires_at: new Date(Date.now() + 300_000).toISOString() };
}

/** An EventSource the test opens, fails and feeds by hand. */
export class FakeEventSource extends EventTarget {
  static instances: FakeEventSource[] = [];
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    super();
    FakeEventSource.instances.push(this);
  }

  static install() {
    FakeEventSource.instances = [];
    vi.stubGlobal('EventSource', FakeEventSource);
  }

  static latest(): FakeEventSource {
    const latest = FakeEventSource.instances.at(-1);
    if (!latest) {
      throw new Error('No EventSource was opened');
    }
    return latest;
  }

  close() {
    this.closed = true;
  }

  open() {
    this.onopen?.();
  }

  fail() {
    this.onerror?.();
  }

  emit(name: string, data: unknown) {
    this.dispatchEvent(new MessageEvent(name, { data: JSON.stringify(data) }));
  }
}

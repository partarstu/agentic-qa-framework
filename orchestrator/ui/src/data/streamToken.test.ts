// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { STREAM_TOKEN_PATH, streamToken, stubRoutes } from '../testing/network';
import { logout } from './authApi';
import { storeSession } from './client';
import { clearStreamToken, getStreamToken } from './streamToken';

const FUTURE = new Date(Date.now() + 3_600_000).toISOString();

describe('getStreamToken', () => {
  let tokens = 0;

  beforeEach(() => {
    localStorage.clear();
    clearStreamToken();
    tokens = 0;
    stubRoutes(({ path }) => (path === STREAM_TOKEN_PATH ? streamToken(`stream-${++tokens}`) : {}));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('reuses the cached token within the same session', async () => {
    storeSession('session-1', FUTURE, 'ops');

    expect(await getStreamToken()).toBe('stream-1');
    expect(await getStreamToken()).toBe('stream-1');
  });

  it('never hands the token of a session that logged out to the next one', async () => {
    storeSession('session-1', FUTURE, 'ops');
    await getStreamToken();

    logout();
    storeSession('session-2', FUTURE, 'other');

    expect(await getStreamToken()).toBe('stream-2');
  });
});

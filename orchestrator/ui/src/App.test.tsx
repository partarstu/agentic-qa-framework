// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { storeSession } from './data/client';
import { clearStreamToken } from './data/streamToken';
import { axeViolations, installDom } from './testing/dom';
import { FakeEventSource, json, STREAM_TOKEN_PATH, streamToken, stubRoutes, type FetchCall } from './testing/network';

installDom();

const FUTURE = new Date(Date.now() + 3_600_000).toISOString();

/** The orchestrator's answers for a signed-in dashboard, with the route's own answer first. */
function stubOrchestrator(route: (call: FetchCall) => unknown = () => undefined) {
  stubRoutes((call) => {
    const answer = route(call);
    if (answer !== undefined) {
      return answer;
    }
    switch (call.path) {
      case '/api/auth/verify':
        return { valid: true, username: 'ops' };
      case STREAM_TOKEN_PATH:
        return streamToken('token');
      case '/api/dashboard/summary':
        return { tasks_total: 3 };
      default:
        return [];
    }
  });
}

async function expectLegalNotice() {
  const notice = await screen.findByRole('contentinfo');
  expect(notice.textContent).toContain('AGPL-3.0');
  expect(screen.getByRole('link', { name: 'Source code' }).getAttribute('href')).toBe('https://github.com/partarstu/agentic-qa-framework');
  expect(screen.getByRole('link', { name: 'Third-party licences' }).getAttribute('href')).toBe('/licenses.md');
}

describe('App', () => {
  beforeEach(() => {
    FakeEventSource.install();
    clearStreamToken();
    localStorage.clear();
  });

  afterEach(() => localStorage.clear());

  it('shows the login with the legal notice without a session', async () => {
    stubOrchestrator();
    render(<App />);

    expect(await screen.findByRole('heading', { name: 'QuAIA™ Orchestrator' })).toBeTruthy();
    expect(screen.getByLabelText('Username')).toBeTruthy();
    await expectLegalNotice();
    expect(await axeViolations()).toEqual([]);
  });

  it('shows the unreachable screen with the legal notice when the orchestrator does not answer', async () => {
    storeSession('token', FUTURE, 'ops');
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }));
    render(<App />);

    expect(await screen.findByText('The orchestrator does not answer')).toBeTruthy();
    await expectLegalNotice();
    expect(await axeViolations()).toEqual([]);
  });

  it('opens the dashboard with the legal notice for a valid session', async () => {
    storeSession('token', FUTURE, 'ops');
    stubOrchestrator();
    render(<App />);

    expect(await screen.findByRole('tablist', { name: 'Dashboard views' })).toBeTruthy();
    await expectLegalNotice();
  });

  it.each([
    [json({ detail: 'Invalid username or password' }, { status: 401 }), 'Wrong username or password.'],
    [json({ detail: 'Too many login attempts.' }, { status: 429, headers: { 'Retry-After': '30' } }), 'Too many attempts. Try again in 30 seconds.'],
    [json({}, { status: 503 }), 'The orchestrator does not answer. Check that it is running, then try again.'],
  ])('says why a login failed', async (answer, message) => {
    stubOrchestrator(({ path }) => (path === '/api/auth/login' ? answer.clone() : undefined));
    const user = userEvent.setup();
    render(<App />);

    await user.type(await screen.findByLabelText('Username'), 'ops');
    await user.type(screen.getByLabelText('Password'), 'secret');
    await user.click(screen.getByRole('button', { name: 'Log in' }));

    expect((await screen.findByRole('alert')).textContent).toBe(message);
    expect(screen.getByLabelText('Password').getAttribute('aria-invalid')).toBe('true');
  });

  it('opens the dashboard after a login and returns to the login when the session is rejected', async () => {
    let rejected = false;
    stubOrchestrator(({ path }) => {
      if (path === '/api/auth/login') {
        return { access_token: 'token', token_type: 'bearer', expires_at: FUTURE };
      }
      return rejected && path.startsWith('/api/dashboard/') ? json({ detail: 'Token expired' }, { status: 401 }) : undefined;
    });
    const user = userEvent.setup();
    render(<App />);
    await user.type(await screen.findByLabelText('Username'), 'ops');
    await user.type(screen.getByLabelText('Password'), 'secret');
    await user.click(screen.getByRole('button', { name: 'Log in' }));
    expect(await screen.findByRole('tablist', { name: 'Dashboard views' })).toBeTruthy();

    rejected = true;
    await user.click(screen.getByRole('tab', { name: 'Tasks' }));

    expect(await screen.findByText('Your session has ended. Log in again.')).toBeTruthy();
    expect(screen.getByLabelText('Username')).toBeTruthy();
  });
});

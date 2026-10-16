// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { storedSession, storeSession } from './data/client';
import { createQueryClient } from './data/queries';
import { clearStreamToken } from './data/streamToken';
import { Shell } from './Shell';
import { axeViolations, installDom } from './testing/dom';
import { FakeEventSource, STREAM_TOKEN_PATH, streamToken, stubRoutes } from './testing/network';
import type { AgentInfo, TaskInfo } from './types/dashboard';

installDom();

const AGENT: AgentInfo = {
  id: 'requirements', name: 'Requirements review', version: '1.2.0', description: '', url: 'http://requirements', status: 'AVAILABLE',
  capabilities: null, running_tasks: [], task_capacity: 1, broken_reason: null, stuck_task_id: null,
};

const TASK: TaskInfo = {
  task_id: 'task-1', agent_id: 'requirements', agent_name: 'Requirements review', description: 'Review story QA-7', status: 'COMPLETED',
  start_time: '2026-10-16T10:00:00Z', end_time: '2026-10-16T10:01:00Z', duration_ms: 60_000, error_message: null, current_activity: null, token_usage: null,
};

const PATHS = {
  agents: '/api/dashboard/agents', summary: '/api/dashboard/summary', tasks: '/api/dashboard/tasks', errors: '/api/dashboard/errors',
  logs: '/api/dashboard/logs', discovery: '/api/dashboard/discovery',
};

let network: ReturnType<typeof stubRoutes>;
let discovery: Promise<unknown>;

function renderShell(onSignedOut = vi.fn()) {
  render(<QueryClientProvider client={createQueryClient()}><Shell onSignedOut={onSignedOut} /></QueryClientProvider>);
  return onSignedOut;
}

const tab = (name: string) => screen.getByRole('tab', { name });
const selected = () => screen.getByRole('tab', { selected: true }).textContent;

describe('Shell', () => {
  beforeEach(() => {
    FakeEventSource.install();
    clearStreamToken();
    discovery = Promise.resolve({ message: '2 agents reachable, 1 unreachable agents removed', reachable: 2, removed: 1 });
    network = stubRoutes(({ path }) => {
      switch (path) {
        case STREAM_TOKEN_PATH:
          return streamToken('token');
        case PATHS.agents:
          return [AGENT];
        case PATHS.summary:
          return { tasks_total: 12 };
        case PATHS.tasks:
          return [TASK];
        case PATHS.discovery:
          return discovery;
        default:
          return [];
      }
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    localStorage.clear();
  });

  it('has no axe violations', async () => {
    renderShell();
    await screen.findByText('12 tasks in the history');

    expect(await axeViolations()).toEqual([]);
    expect(screen.getByRole('contentinfo').textContent).toContain('Source code');
  });

  it('leads the Tab order with the skip link, then the selected view and the tools', async () => {
    const user = userEvent.setup();
    renderShell();

    const names: (string | null)[] = [];
    for (let step = 0; step < 5; step += 1) {
      await user.tab();
      names.push(document.activeElement?.textContent ?? null);
    }

    expect(names).toEqual(['Skip to the content', 'Overview', expect.stringContaining('Search and jump'), 'Preferences', 'Log out']);
    expect(screen.getByRole('link', { name: 'Skip to the content' }).getAttribute('href')).toBe('#dashboard-main');
    expect(screen.getByRole('main').tabIndex).toBe(-1);
  });

  it('moves along the views with the arrow keys and selects one with Enter', async () => {
    const user = userEvent.setup();
    renderShell();
    await user.click(tab('Overview'));

    await user.keyboard('{ArrowRight}{ArrowRight}');
    expect(document.activeElement).toBe(tab('Tasks'));
    expect(selected()).toBe('Overview');
    await user.keyboard('{Enter}');

    expect(selected()).toBe('Tasks');
    expect(await screen.findByText('1 of the last 100 tasks loaded')).toBeTruthy();
  });

  it('opens Search and jump with Ctrl+K and closes it with Escape', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.keyboard('{Control>}k{/Control}');
    const field = screen.getByRole('combobox', { name: 'Search and jump' });
    expect(document.activeElement).toBe(field);

    await user.keyboard('{Escape}');

    expect(screen.queryByRole('combobox')).toBeNull();
    expect((document.querySelector('dialog.palette') as HTMLDialogElement).open).toBe(false);
  });

  it('goes to a view with G and its letter, and shows the shortcuts with ? until Escape', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.keyboard('ge');
    expect(selected()).toBe('Errors');

    await user.keyboard('?');
    expect(screen.getByRole('dialog', { name: 'Keyboard shortcuts' })).toBeTruthy();
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('dialog', { name: 'Keyboard shortcuts' })).toBeNull();
  });

  it('sends no request for a view hidden by Activity', async () => {
    vi.useFakeTimers();
    renderShell();
    await act(() => vi.advanceTimersByTimeAsync(0));
    fireEvent.click(tab('Tasks'));
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(network.count(PATHS.tasks)).toBe(1);

    fireEvent.click(tab('Overview'));
    await act(() => vi.advanceTimersByTimeAsync(0));
    const summaries = network.count(PATHS.summary);
    await act(() => vi.advanceTimersByTimeAsync(35_000));

    expect(network.count(PATHS.tasks)).toBe(1);
    expect(network.count(PATHS.errors)).toBe(0);
    expect(network.count(PATHS.logs)).toBe(0);
    expect(network.count(PATHS.summary)).toBeGreaterThan(summaries);
  });

  it('offers the agents and, only while it is open, the loaded tasks in Search and jump', async () => {
    const user = userEvent.setup();
    renderShell();
    await screen.findByText('12 tasks in the history');
    expect(network.count(PATHS.tasks)).toBe(0);

    await user.click(screen.getByRole('button', { name: /Search and jump/ }));
    const list = screen.getByRole('listbox', { name: 'Commands' });

    expect(await within(list).findByRole('option', { name: /Review story QA-7/ })).toBeTruthy();
    expect(within(list).getByRole('option', { name: /Requirements review\s*Agent$/ })).toBeTruthy();

    await user.keyboard('review story{Enter}');
    expect(selected()).toBe('Tasks');
  });

  it('runs the discovery from Search and jump and keeps its result until dismissed', async () => {
    let finish: (value: unknown) => void = () => undefined;
    discovery = new Promise((resolve) => {
      finish = resolve;
    });
    const user = userEvent.setup();
    renderShell();
    await user.keyboard('{Control>}k{/Control}discover{Enter}');

    expect(await screen.findByText(/Discovering agents/)).toBeTruthy();
    await act(async () => finish({ message: '2 agents reachable, 1 unreachable agents removed', reachable: 2, removed: 1 }));

    const result = await screen.findByText('Agent discovery: 2 agents reachable, 1 unreachable agents removed');
    expect(result.closest('[role="status"]')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByText(/Agent discovery:/)).toBeNull();
  });

  it('says politely that the orchestrator is unreachable while requests fail', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }));
    renderShell();

    const status = await screen.findByText('Orchestrator unreachable, retrying');

    expect(status.closest('[role="status"]')).toBeTruthy();
  });

  it('shows the state of the stream and announces task starts and ends in a polite live region', async () => {
    renderShell();
    await act(() => Promise.resolve());
    const stream = FakeEventSource.latest();

    act(() => stream.open());

    expect(screen.getByText('Live')).toBeTruthy();
    expect(document.querySelector('[aria-live="polite"]')).toBeTruthy();
  });

  it('logs out', async () => {
    storeSession('token', new Date(Date.now() + 60_000).toISOString(), 'ops');
    const user = userEvent.setup();
    const onSignedOut = renderShell();

    await user.click(screen.getByRole('button', { name: 'Log out' }));

    expect(onSignedOut).toHaveBeenCalledOnce();
    expect(storedSession()).toBeNull();
  });
});

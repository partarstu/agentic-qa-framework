// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { INITIAL_LIVE_STATE } from '../../live/liveState';
import { axeViolations, installDom } from '../../testing/dom';
import { agent, summary, task } from '../../testing/fixtures';
import { json, stubRoutes } from '../../testing/network';
import { renderView } from '../../testing/render';
import type { DashboardSummary, RagSyncOutcome, TaskInfo } from '../../types/dashboard';
import { KpiValue, OverviewView, successTrend } from './OverviewView';

installDom();

let summaryAnswer: DashboardSummary | Promise<never> | Response;
let tasks: TaskInfo[] = [];
let syncs: RagSyncOutcome[] = [];

const SYNC: RagSyncOutcome = {
  sync_type: 'jira', scope: 'QA', status: 'completed_with_errors', processed_count: 42, message: '2 issues skipped',
  updated_at: '2026-10-16T09:00:00Z', stale: true,
};

const LIVE = {
  ...INITIAL_LIVE_STATE,
  running: { 'task-5': { task_id: 'task-5', agent_id: 'ui', current_activity: 'Clicking Save' } },
  activity: [
    { key: 1, task_id: 'task-5', agent_id: 'ui', text: 'Opening the page', receivedAt: Date.parse('2026-10-16T12:00:00Z') },
    { key: 2, task_id: 'task-5', agent_id: 'ui', text: 'Clicking Save', receivedAt: Date.parse('2026-10-16T12:00:05Z') },
  ],
};

const statuses = (completed: number, failed: number) => [
  ...Array.from({ length: completed }, (_, index) => task({ task_id: `ok-${index}`, status: 'COMPLETED', start_time: `2026-10-16T10:${String(index).padStart(2, '0')}:00Z` })),
  ...Array.from({ length: failed }, (_, index) => task({ task_id: `ko-${index}`, status: 'FAILED', start_time: `2026-10-16T11:${String(index).padStart(2, '0')}:00Z` })),
];

describe('successTrend', () => {
  it('rates the finished tasks oldest first in groups of ten, leaving out the running ones', () => {
    const tasksInOrder = [...statuses(10, 5), task({ task_id: 'running', status: 'RUNNING', start_time: '2026-10-16T12:00:00Z' })];

    expect(successTrend(tasksInOrder)).toEqual([100, 0]);
  });

  it('has no point without finished tasks', () => {
    expect(successTrend([task({ status: 'RUNNING' })])).toEqual([]);
  });
});

describe('KpiValue', () => {
  it('mounts a changed figure afresh, so its entry animation replays, and keeps an unchanged one', () => {
    const { container, rerender } = render(<KpiValue>12</KpiValue>);
    const first = container.querySelector('.kpi-value');

    rerender(<KpiValue>12</KpiValue>);
    expect(container.querySelector('.kpi-value')).toBe(first);

    rerender(<KpiValue>13</KpiValue>);
    expect(container.querySelector('.kpi-value')).not.toBe(first);
    expect(container.textContent).toBe('13');
  });
});

describe('OverviewView', () => {
  beforeEach(() => {
    summaryAnswer = summary();
    tasks = [];
    syncs = [];
    stubRoutes(({ path }) => {
      switch (path) {
        case '/api/dashboard/summary':
          return summaryAnswer;
        case '/api/dashboard/agents':
          return [agent(), agent({ id: 'ui', name: 'UI test execution', status: 'BUSY' }), agent({ id: 'incident', name: 'Incident creation', status: 'BROKEN' })];
        case '/api/dashboard/tasks':
          return tasks;
        case '/api/dashboard/rag-sync-status':
          return syncs;
        default:
          return [];
      }
    });
  });

  it('shows the key figures, the topology, the live activity, the latest failures and the knowledge sync', async () => {
    tasks = [
      task({ task_id: 'task-1', status: 'FAILED', description: 'Review story QA-7', error_message: 'Jira did not answer', start_time: '2026-10-16T10:00:00Z' }),
      task({ task_id: 'task-2', status: 'COMPLETED', start_time: '2026-10-16T09:00:00Z' }),
    ];
    syncs = [SYNC];
    const { navigation } = renderView(<OverviewView />, { live: LIVE });

    expect(await screen.findByText(/^90\s?%$/)).toBeTruthy();
    expect(screen.getByText('9 of 10 finished tasks')).toBeTruthy();
    expect(screen.getByText('Line: last 100 tasks')).toBeTruthy();
    expect(await screen.findByRole('img', { name: /^Success rate of the last 100 tasks, in groups of ten: 50\s?%$/ })).toBeTruthy();
    expect(screen.getByText(/3[.,]41/)).toBeTruthy();
    expect(screen.getByText(/^1[.,]2M tokens over 10 retained tasks$/)).toBeTruthy();
    expect(screen.getByText('Version 4.0.0, model gemini-3-flash')).toBeTruthy();
    expect(within(screen.getByRole('list', { name: 'Agents by status' })).getAllByRole('listitem').map((item) => item.textContent))
      .toEqual(['1 available', '1 busy', '1 broken']);
    expect(await screen.findByText('UI test execution: Busy, 1 task running')).toBeTruthy();

    const feed = screen.getByRole('region', { name: 'Live activity' });
    expect([...feed.querySelectorAll('.activity-text')].map((item) => item.textContent)).toEqual(['Clicking Save', 'Opening the page']);
    expect(feed.getAttribute('aria-live')).toBeNull();

    expect(screen.getByText('Jira did not answer')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Review story QA-7' }));
    expect(navigation.openTask).toHaveBeenCalledWith('task-1');

    expect(await screen.findByText('Completed with errors')).toBeTruthy();
    expect(screen.getByText('Stale')).toBeTruthy();
    expect(screen.getByText('2 issues skipped')).toBeTruthy();
    expect(await axeViolations()).toEqual([]);
  });

  it('says what is still empty: no finished task, no price, no activity, no failure and no sync', async () => {
    summaryAnswer = summary({ tasks_completed: 0, tasks_failed: 0, tasks_total: 0, tokens_total: 0, cost_usd_total: null });
    renderView(<OverviewView />);

    expect(await screen.findByText('No finished task yet')).toBeTruthy();
    expect(screen.getByText('Not priced')).toBeTruthy();
    expect(screen.getByText('No activity since this page opened.')).toBeTruthy();
    expect(await screen.findByText('No failed task among the last 100.')).toBeTruthy();
    expect(await screen.findByText('No knowledge sync has run.')).toBeTruthy();
    expect(screen.getByText('No data yet')).toBeTruthy();
    expect(await axeViolations()).toEqual([]);
  });

  it('shows the loading and the error state of the key figures', async () => {
    summaryAnswer = new Promise<never>(() => undefined);
    renderView(<OverviewView />);
    expect(screen.getByText('Loading the key figures…')).toBeTruthy();

    summaryAnswer = json({ detail: 'Bad request' }, { status: 400 });
    renderView(<OverviewView />);
    expect((await screen.findByRole('alert')).textContent).toContain('The orchestrator did not answer');
  });
});

// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { fireEvent, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { axeViolations, installDom } from '../../testing/dom';
import { task } from '../../testing/fixtures';
import { json, stubRoutes } from '../../testing/network';
import { renderView } from '../../testing/render';
import type { TaskInfo } from '../../types/dashboard';
import { TasksView } from './TasksView';

installDom();

let tasks: TaskInfo[] | Promise<never> | Response = [];

const usage = (total: number, cost: number | null) => ({
  model_name: 'gemini-3-flash', input_tokens: total, output_tokens: 0, total_tokens: total, cache_read_tokens: 0, requests: 1, tool_calls: 0, cost_usd: cost,
});

const TASKS = [
  task({ task_id: 'task-1', description: 'Review story QA-7', start_time: '2026-10-16T10:00:00Z', duration_ms: 60_000, token_usage: usage(500, 0.01) }),
  task({ task_id: 'task-2', description: 'Run TC-1', agent_id: 'ui', agent_name: 'UI test execution', status: 'FAILED', start_time: '2026-10-16T11:00:00Z',
    duration_ms: 5_000, token_usage: usage(2_000, null) }),
  task({ task_id: 'task-3', description: 'Review story QA-8', status: 'RUNNING', start_time: '2026-10-16T12:00:00Z', end_time: null, duration_ms: null }),
];

const rowNames = () => screen.getAllByRole('rowheader').map((cell) => cell.textContent);

describe('TasksView', () => {
  beforeEach(() => {
    stubRoutes(() => tasks);
  });

  it('lists the tasks newest first in a captioned table with scoped headers', async () => {
    tasks = TASKS;
    renderView(<TasksView />);

    expect(await screen.findByRole('table', { name: 'The last 100 tasks, the most the orchestrator returns' })).toBeTruthy();
    expect(rowNames()).toEqual(['Review story QA-8', 'Run TC-1', 'Review story QA-7']);
    expect(screen.getByRole('columnheader', { name: /Started/ }).getAttribute('aria-sort')).toBe('descending');
    const failed = screen.getByRole('row', { name: /Run TC-1/ });
    expect(within(failed).getByText('Failed')).toBeTruthy();
    expect(within(failed).getByText('Not priced')).toBeTruthy();
    expect(await axeViolations()).toEqual([]);
  });

  it('sorts by a column, reversing on a second click, with the missing figures last', async () => {
    tasks = TASKS;
    renderView(<TasksView />);
    await screen.findByRole('table');

    fireEvent.click(screen.getByRole('button', { name: 'Tokens' }));
    expect(screen.getByRole('columnheader', { name: /Tokens/ }).getAttribute('aria-sort')).toBe('ascending');
    expect(rowNames()).toEqual(['Review story QA-7', 'Run TC-1', 'Review story QA-8']);

    fireEvent.click(screen.getByRole('button', { name: /Tokens/ }));
    expect(rowNames()).toEqual(['Run TC-1', 'Review story QA-7', 'Review story QA-8']);
    expect(screen.getByRole('columnheader', { name: /Started/ }).getAttribute('aria-sort')).toBeNull();
  });

  it('filters by status, agent and text, and says when nothing matches', async () => {
    tasks = TASKS;
    renderView(<TasksView />);
    await screen.findByRole('table');

    fireEvent.change(screen.getByRole('combobox', { name: 'Agent' }), { target: { value: 'requirements' } });
    expect(rowNames()).toEqual(['Review story QA-8', 'Review story QA-7']);
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search the tasks' }), { target: { value: 'qa-7' } });
    expect(rowNames()).toEqual(['Review story QA-7']);
    expect(screen.getByText('1 of 3 tasks')).toBeTruthy();
    fireEvent.change(screen.getByRole('combobox', { name: 'Status' }), { target: { value: 'FAILED' } });

    expect(screen.getByText('No task matches the filters.')).toBeTruthy();
  });

  it('opens the task sheet from a row', async () => {
    tasks = TASKS;
    const { navigation } = renderView(<TasksView />);

    fireEvent.click(await screen.findByRole('button', { name: 'Run TC-1' }));

    expect(navigation.openTask).toHaveBeenCalledWith('task-2');
  });

  it('says that there are no tasks yet', async () => {
    tasks = [];
    renderView(<TasksView />);

    expect(await screen.findByText('No tasks yet')).toBeTruthy();
    expect(await axeViolations()).toEqual([]);
  });

  it('shows the loading and the error state', async () => {
    tasks = new Promise<never>(() => undefined);
    renderView(<TasksView />);
    expect(screen.getByText('Loading the tasks…')).toBeTruthy();

    tasks = json({ detail: 'Bad request' }, { status: 400 });
    renderView(<TasksView />);
    expect((await screen.findByRole('alert')).textContent).toContain('The orchestrator did not answer');
  });
});

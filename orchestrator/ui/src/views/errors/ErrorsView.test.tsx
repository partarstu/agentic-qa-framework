// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { fireEvent, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { axeViolations, installDom } from '../../testing/dom';
import { agent, error, task } from '../../testing/fixtures';
import { json, stubRoutes } from '../../testing/network';
import { renderView } from '../../testing/render';
import type { ErrorInfo } from '../../types/dashboard';
import { ErrorsView, groupErrors } from './ErrorsView';

installDom();

let errors: ErrorInfo[] | Promise<never> | Response = [];

const ERRORS = [
  error({ error_id: 'e1', timestamp: '2026-10-16T10:00:00Z', task_id: 'task-1', message: 'Jira did not answer' }),
  error({ error_id: 'e2', timestamp: '2026-10-16T11:00:00Z', task_id: 'task-old', message: 'Qdrant refused the batch', traceback_snippet: 'QdrantError: too large' }),
  error({ error_id: 'e3', timestamp: '2026-10-16T12:00:00Z', task_id: null, agent_id: null, module: 'orchestrator.discovery', message: 'Agent probe failed' }),
];

describe('ErrorsView', () => {
  beforeEach(() => {
    stubRoutes(({ path }) => {
      switch (path) {
        case '/api/dashboard/errors':
          return errors;
        case '/api/dashboard/tasks':
          return [task({ task_id: 'task-1' })];
        case '/api/dashboard/agents':
          return [agent()];
        default:
          return [];
      }
    });
  });

  it('groups the errors by module and agent, the group of the newest error first', () => {
    const groups = groupErrors(ERRORS, (agentId) => `Agent ${agentId}`);

    expect(groups.map(({ module, agent: name, errors: grouped }) => [module, name, grouped.map(({ error_id }) => error_id)])).toEqual([
      ['orchestrator.discovery', 'Orchestrator', ['e3']],
      ['orchestrator.main', 'Agent requirements', ['e2', 'e1']],
    ]);
  });

  it('links an error to its task among the loaded 100 and keeps the message and traceback of one outside them', async () => {
    errors = ERRORS;
    const { navigation } = renderView(<ErrorsView />);

    const group = (await screen.findByRole('heading', { name: /orchestrator\.main · Requirements review/ })).closest('section')!;
    expect(within(group).getByText('2 errors')).toBeTruthy();
    const outside = within(group).getByText('Qdrant refused the batch').closest('li')!;
    expect(await within(outside).findByText('Not among the last 100 tasks')).toBeTruthy();
    fireEvent.click(within(outside).getByText('Traceback'));
    expect(within(outside).getByText('QdrantError: too large')).toBeTruthy();

    fireEvent.click(within(group).getByRole('button', { name: 'Open the task' }));
    expect(navigation.openTask).toHaveBeenCalledWith('task-1');
    expect(await axeViolations()).toEqual([]);
  });

  it('says that no error is recorded', async () => {
    errors = [];
    renderView(<ErrorsView />);

    expect(await screen.findByText('No errors recorded')).toBeTruthy();
    expect(await axeViolations()).toEqual([]);
  });

  it('shows the loading and the error state', async () => {
    errors = new Promise<never>(() => undefined);
    renderView(<ErrorsView />);
    expect(screen.getByText('Loading the errors…')).toBeTruthy();

    errors = json({ detail: 'Bad request' }, { status: 400 });
    renderView(<ErrorsView />);
    expect((await screen.findByRole('alert')).textContent).toContain('The orchestrator did not answer');
  });
});

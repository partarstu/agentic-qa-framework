// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { fireEvent, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { INITIAL_LIVE_STATE } from '../../live/liveState';
import { axeViolations, installDom } from '../../testing/dom';
import { agent } from '../../testing/fixtures';
import { json, stubRoutes } from '../../testing/network';
import { renderView } from '../../testing/render';
import type { AgentInfo } from '../../types/dashboard';
import { AgentsView } from './AgentsView';

installDom();

let agents: AgentInfo[] | Promise<never> | Response = [];

const AGENTS = [
  agent({ description: '<ul><li>Reviews stories</li></ul><a href="javascript:alert(1)">docs</a><script>alert(2)</script>' }),
  agent({ id: 'ui', name: 'UI test execution', status: 'BUSY', task_capacity: 1,
    running_tasks: [{ task_id: 'task-2', description: 'Run TC-1', start_time: '2026-10-16T10:00:00Z' }] }),
  agent({ id: 'incident', name: 'Incident creation', status: 'BROKEN', broken_reason: 'TASK_STUCK', stuck_task_id: 'task-9' }),
];

describe('AgentsView', () => {
  beforeEach(() => {
    stubRoutes(() => agents);
  });

  it('shows a card per agent with its status, capacity, live activity, version and sanitised description', async () => {
    agents = AGENTS;
    renderView(<AgentsView />, {
      live: { ...INITIAL_LIVE_STATE, running: { 'task-2': { task_id: 'task-2', agent_id: 'ui', current_activity: 'Clicking Save' } } },
    });

    const card = (await screen.findByRole('button', { name: 'UI test execution' })).closest('li')!;
    expect(within(card).getByText('Busy')).toBeTruthy();
    expect(within(card).getByRole('meter', { name: 'Capacity' }).getAttribute('aria-valuetext')).toBe('1 of 1 slot busy');
    expect(within(card).getByText('Clicking Save')).toBeTruthy();
    expect(screen.getByText('3 agents registered')).toBeTruthy();
    const description = document.querySelector('.agent-description')!;
    expect(description.querySelector('li')?.textContent).toBe('Reviews stories');
    expect(description.innerHTML).not.toMatch(/script|javascript:/);
    expect(await axeViolations()).toEqual([]);
  });

  it('opens the agent sheet from its card and the stuck task from a broken agent', async () => {
    agents = AGENTS;
    const { navigation } = renderView(<AgentsView />);

    fireEvent.click(await screen.findByRole('button', { name: 'Requirements review' }));
    fireEvent.click(screen.getByRole('button', { name: 'Open the stuck task' }));

    expect(navigation.openAgent).toHaveBeenCalledWith('requirements');
    expect(navigation.openTask).toHaveBeenCalledWith('task-9');
    expect(screen.getByText('Task stuck')).toBeTruthy();
  });

  it('runs the discovery', () => {
    agents = AGENTS;
    const { navigation } = renderView(<AgentsView />);

    fireEvent.click(screen.getByRole('button', { name: 'Discover agents' }));

    expect(navigation.discover).toHaveBeenCalledOnce();
  });

  it('shows the discovery running while the shell has none to offer', () => {
    agents = AGENTS;
    renderView(<AgentsView />, { navigation: { discover: null } });

    const button = screen.getByRole<HTMLButtonElement>('button', { name: 'Discover agents' });
    expect(button.getAttribute('aria-busy')).toBe('true');
    expect(button.disabled).toBe(true);
  });

  it('says that no agent is registered', async () => {
    agents = [];
    renderView(<AgentsView />);

    expect(await screen.findByText('No agents registered')).toBeTruthy();
    expect(await axeViolations()).toEqual([]);
  });

  it('shows the loading and the error state', async () => {
    agents = new Promise<never>(() => undefined);
    renderView(<AgentsView />);
    expect(screen.getByText('Loading the agents…')).toBeTruthy();

    agents = json({ detail: 'Bad request' }, { status: 400 });
    renderView(<AgentsView />);
    expect((await screen.findByRole('alert')).textContent).toContain('The orchestrator did not answer');
  });
});

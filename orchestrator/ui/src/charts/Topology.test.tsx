// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { agent } from '../testing/fixtures';
import { axeViolations, installDom } from '../testing/dom';
import { Topology } from './Topology';

installDom();

const AGENTS = [
  agent({ id: 'requirements', name: 'Requirements review' }),
  agent({ id: 'ui', name: 'UI test execution', running_tasks: [{ task_id: 'task-1', description: 'Run TC-1', start_time: '2026-10-16T10:00:00Z' }] }),
  agent({ id: 'incident', name: 'Incident creation', status: 'BROKEN', broken_reason: 'OFFLINE' }),
];

describe('Topology', () => {
  it('lights the edge of an agent with a running task and lists every agent with its state for a screen reader', async () => {
    render(<Topology agents={AGENTS} running={{ 'task-2': { task_id: 'task-2', agent_id: 'ui', current_activity: null } }} />);

    expect(document.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true');
    expect([...document.querySelectorAll('.topology-edge')].map((edge) => edge.getAttribute('class'))).toEqual([
      'topology-edge topology-edge-available', 'topology-edge topology-edge-busy', 'topology-edge topology-edge-broken',
    ]);
    expect(screen.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      'Requirements review: Available', 'UI test execution: Busy, 2 tasks running', 'Incident creation: Broken',
    ]);
    expect(await axeViolations()).toEqual([]);
  });

  it('marks an agent busy from the live store before its poll lists the task', () => {
    render(<Topology agents={[AGENTS[0]]} running={{ 'task-3': { task_id: 'task-3', agent_id: 'requirements', current_activity: 'Reading' } }} />);

    expect(screen.getByRole('listitem').textContent).toBe('Requirements review: Busy, 1 task running');
  });

  it('says that no agent is registered', async () => {
    render(<Topology agents={[]} running={{}} />);

    expect(screen.getByText('No agents registered.')).toBeTruthy();
    expect(await axeViolations()).toEqual([]);
  });
});

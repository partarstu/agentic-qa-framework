// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { describe, expect, it } from 'vitest';
import { ACTIVITY_LIMIT, applyLiveEvent, INITIAL_LIVE_STATE, SEEN_LIMIT, type LiveEvent, type LiveState } from './liveState';

const RUNNING = { task_id: 'task-1', agent_id: 'design', description: 'Design tests', current_activity: 'Reading the story' };

function run(events: LiveEvent[], state: LiveState = INITIAL_LIVE_STATE) {
  const started: string[] = [];
  const ended: string[] = [];
  for (const event of events) {
    const outcome = applyLiveEvent(state, event);
    state = outcome.state;
    started.push(...outcome.started);
    ended.push(...outcome.ended);
  }
  return { state, started, ended };
}

const activity = (task_id: string, text = 'Working'): LiveEvent => ({ type: 'activity', task_id, agent_id: 'design', text, receivedAt: 1 });
const snapshot = (...tasks: (typeof RUNNING)[]): LiveEvent => ({ type: 'snapshot', tasks });
const poll = (...taskIds: string[]): LiveEvent => ({ type: 'poll', tasks: taskIds.map((task_id) => ({ task_id, agent_id: 'design' })) });

describe('applyLiveEvent', () => {
  it('takes the running tasks of a snapshot without announcing them', () => {
    const { state, started } = run([snapshot(RUNNING)]);

    expect(state.running).toEqual({ 'task-1': { task_id: 'task-1', agent_id: 'design', current_activity: 'Reading the story' } });
    expect(state.synced).toBe(true);
    expect(started).toEqual([]);
  });

  it('replaces the running tasks with those of a later snapshot', () => {
    const { state } = run([snapshot(RUNNING), activity('task-2'), snapshot({ ...RUNNING, task_id: 'task-3' })]);

    expect(Object.keys(state.running)).toEqual(['task-3']);
  });

  it('starts a task first seen in an activity event and updates it with the next', () => {
    const { state, started } = run([snapshot(), activity('task-2', 'Reading'), activity('task-2', 'Writing')]);

    expect(started).toEqual(['task-2']);
    expect(state.running['task-2'].current_activity).toBe('Writing');
    expect(state.activity.map(({ text, key }) => [key, text])).toEqual([[1, 'Reading'], [2, 'Writing']]);
  });

  it(`keeps the last ${ACTIVITY_LIMIT} activity events`, () => {
    const events = Array.from({ length: ACTIVITY_LIMIT + 5 }, (_, index) => activity('task-1', `step ${index}`));

    const { state } = run([snapshot(RUNNING), ...events]);

    expect(state.activity).toHaveLength(ACTIVITY_LIMIT);
    expect(state.activity[0].text).toBe('step 5');
    expect(state.activity.at(-1)?.text).toBe(`step ${ACTIVITY_LIMIT + 4}`);
  });

  it('starts a task first seen running in the agents poll', () => {
    const { state, started } = run([snapshot(), poll('task-2')]);

    expect(started).toEqual(['task-2']);
    expect(state.running['task-2']).toEqual({ task_id: 'task-2', agent_id: 'design', current_activity: null });
  });

  it('records the tasks of a poll before the first snapshot silently', () => {
    const { state, started } = run([poll('task-1'), snapshot(RUNNING), poll('task-1')]);

    expect(started).toEqual([]);
    expect(state.seen).toEqual(['task-1']);
  });

  it('neither announces nor runs again a finished task that a poll still lists', () => {
    const { state, started, ended } = run([snapshot(), activity('task-2'), { type: 'done', task_id: 'task-2', status: 'COMPLETED' }, poll('task-2')]);

    expect(started).toEqual(['task-2']);
    expect(ended).toEqual(['COMPLETED']);
    expect(state.running).toEqual({});
  });

  it('does not run a finished task again on a late activity event', () => {
    const { state } = run([snapshot(), activity('task-2'), { type: 'done', task_id: 'task-2', status: 'FAILED' }, activity('task-2', 'late')]);

    expect(state.running).toEqual({});
    expect(state.activity.at(-1)?.text).toBe('late');
  });

  it('ends a task the polled task list reports finished', () => {
    const { state, ended } = run([snapshot(RUNNING), { type: 'reconcile', terminalTaskIds: ['task-1', 'task-9'] }]);

    expect(state.running).toEqual({});
    expect(ended).toEqual([]);
  });

  it(`remembers the newest ${SEEN_LIMIT} task ids`, () => {
    const many = Array.from({ length: SEEN_LIMIT + 1 }, (_, index) => `task-${index}`);

    const { state } = run([snapshot(), poll(...many)]);

    expect(state.seen).toHaveLength(SEEN_LIMIT);
    expect(state.seen[0]).toBe('task-1');
  });
});

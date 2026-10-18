// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import type { RunningTaskSnapshot, TaskInfo } from '../types/dashboard';

export const ACTIVITY_LIMIT = 200;
export const SEEN_LIMIT = 1_000;

export interface LiveTask {
  task_id: string;
  agent_id: string;
  current_activity: string | null;
}

/** An `agent_activity` event as received; events carry no time of their own, so `receivedAt` is when this page got it. */
export interface ActivityEntry {
  key: number;
  task_id: string;
  agent_id: string;
  text: string;
  receivedAt: number;
}

export interface LiveState {
  running: Record<string, LiveTask>;
  /** The newest last, at most ACTIVITY_LIMIT. */
  activity: ActivityEntry[];
  /** Every task id this page has seen, finished ones included, the newest last, at most SEEN_LIMIT. */
  seen: string[];
  /** Whether the first snapshot arrived; until then, the task ids of a poll are recorded without an announcement. */
  synced: boolean;
}

export const INITIAL_LIVE_STATE: LiveState = { running: {}, activity: [], seen: [], synced: false };

export type LiveEvent =
  | { type: 'snapshot'; tasks: RunningTaskSnapshot[] }
  | { type: 'activity'; task_id: string; agent_id: string; text: string; receivedAt: number }
  | { type: 'done'; task_id: string; status: TaskInfo['status'] }
  | { type: 'poll'; tasks: Array<{ task_id: string; agent_id: string }> }
  | { type: 'reconcile'; terminalTaskIds: string[] };

export interface LiveOutcome {
  state: LiveState;
  /** Tasks this event showed running for the first time. */
  started: string[];
  ended: TaskInfo['status'][];
}

export function applyLiveEvent(state: LiveState, event: LiveEvent): LiveOutcome {
  const unchanged: LiveOutcome = { state, started: [], ended: [] };
  switch (event.type) {
    case 'snapshot':
      return {
        state: {
          ...state,
          running: Object.fromEntries(event.tasks.map(({ task_id, agent_id, current_activity }) => [task_id, { task_id, agent_id, current_activity }])),
          seen: remember(state.seen, event.tasks.map(({ task_id }) => task_id)),
          synced: true,
        },
        started: [],
        ended: [],
      };
    case 'activity': {
      const { task_id, agent_id, text, receivedAt } = event;
      const isNew = !state.seen.includes(task_id);
      const previousKey = state.activity.at(-1)?.key ?? 0;
      const activity = [...state.activity, { key: previousKey + 1, task_id, agent_id, text, receivedAt }].slice(-ACTIVITY_LIMIT);
      // A late event of a task that already finished never makes it run again
      const running = isNew || task_id in state.running ? { ...state.running, [task_id]: { task_id, agent_id, current_activity: text } } : state.running;
      return { state: { ...state, running, activity, seen: remember(state.seen, [task_id]) }, started: isNew ? [task_id] : [], ended: [] };
    }
    case 'done': {
      const { [event.task_id]: _done, ...running } = state.running;
      return { state: { ...state, running, seen: remember(state.seen, [event.task_id]) }, started: [], ended: [event.status] };
    }
    case 'poll': {
      const fresh = event.tasks.filter(({ task_id }) => !state.seen.includes(task_id));
      if (fresh.length === 0) {
        return unchanged;
      }
      const seen = remember(state.seen, fresh.map(({ task_id }) => task_id));
      if (!state.synced) {
        return { state: { ...state, seen }, started: [], ended: [] };
      }
      const running = { ...state.running };
      for (const { task_id, agent_id } of fresh) {
        running[task_id] = { task_id, agent_id, current_activity: null };
      }
      return { state: { ...state, running, seen }, started: fresh.map(({ task_id }) => task_id), ended: [] };
    }
    case 'reconcile': {
      const finished = event.terminalTaskIds.filter((taskId) => taskId in state.running);
      if (finished.length === 0) {
        return unchanged;
      }
      const running = { ...state.running };
      finished.forEach((taskId) => delete running[taskId]);
      return { state: { ...state, running }, started: [], ended: [] };
    }
  }
}

function remember(seen: string[], taskIds: string[]): string[] {
  const added = taskIds.filter((taskId, index) => !seen.includes(taskId) && taskIds.indexOf(taskId) === index);
  return added.length === 0 ? seen : [...seen, ...added].slice(-SEEN_LIMIT);
}

// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { createContext, useContext, useEffect, useState } from 'react';
import { QUERY_KEYS, type QueryName } from '../data/queries';
import type { AgentActivityPayload, AgentInfo, SnapshotPayload, TaskDonePayload, TaskInfo } from '../types/dashboard';
import { createAnnouncer, createInvalidator } from './batching';
import { applyLiveEvent, INITIAL_LIVE_STATE, type LiveEvent, type LiveState } from './liveState';
import { useEventStream, type StreamEventName } from './useEventStream';

const TERMINAL_STATUSES = new Set<TaskInfo['status']>(['COMPLETED', 'FAILED', 'CANCELLED']);
const ON_TASK_END: QueryName[] = ['tasks', 'summary', 'agents', 'errors'];

const LiveContext = createContext<LiveState>(INITIAL_LIVE_STATE);

export const LiveProvider = LiveContext.Provider;

/** The running tasks and the activity received since the page opened, for the views under the shell. */
export function useLive(): LiveState {
  return useContext(LiveContext);
}

/**
 * Feeds the live store and turns its task starts and ends into batched announcements and refreshes of the queries they change;
 * a reconnect's snapshot or a gap refreshes every query, as events may have been lost.
 */
function createLiveController(queryClient: QueryClient, onState: (state: LiveState) => void, onAnnounce: (text: string) => void) {
  let state = INITIAL_LIVE_STATE;
  let snapshots = 0;
  const announcer = createAnnouncer(onAnnounce);
  const invalidator = createInvalidator(queryClient);

  const apply = (event: LiveEvent, onStart: QueryName[]) => {
    const outcome = applyLiveEvent(state, event);
    state = outcome.state;
    onState(state);
    announcer.queue(outcome.started.length, outcome.ended);
    if (outcome.started.length > 0) {
      invalidator.invalidate(onStart);
    }
    if (outcome.ended.length > 0) {
      invalidator.invalidate(ON_TASK_END);
    }
  };

  return {
    onAgents(agents: AgentInfo[]) {
      apply({ type: 'poll', tasks: agents.flatMap(({ id, running_tasks }) => running_tasks.map(({ task_id }) => ({ task_id, agent_id: id }))) }, ['tasks', 'summary']);
    },
    onTasks(tasks: TaskInfo[]) {
      apply({ type: 'reconcile', terminalTaskIds: tasks.filter(({ status }) => TERMINAL_STATUSES.has(status)).map(({ task_id }) => task_id) }, []);
    },
    onStreamEvent(name: StreamEventName, data: unknown) {
      switch (name) {
        case 'snapshot':
          snapshots += 1;
          apply({ type: 'snapshot', tasks: (data as SnapshotPayload).running_tasks }, []);
          if (snapshots > 1) {
            invalidator.invalidate('all');
          }
          break;
        case 'agent_activity': {
          const { task_id, agent_id, text } = data as AgentActivityPayload;
          apply({ type: 'activity', task_id, agent_id, text, receivedAt: Date.now() }, ['tasks', 'summary', 'agents']);
          break;
        }
        case 'task_done': {
          const { task_id, status } = data as TaskDonePayload;
          apply({ type: 'done', task_id, status }, []);
          break;
        }
        case 'gap':
          invalidator.invalidate('all');
          break;
      }
    },
    dispose() {
      announcer.dispose();
      invalidator.dispose();
    },
  };
}

/** The shell's live store, fed by the global stream and by the shell's agents poll, with the polite announcement of task starts and ends. */
export function useLiveDashboard(agents: AgentInfo[] | undefined) {
  const queryClient = useQueryClient();
  const [live, setLive] = useState(INITIAL_LIVE_STATE);
  const [announcement, setAnnouncement] = useState('');
  // A repeated sentence gets a different text, or the live region would not read it again
  const [controller] = useState(() => createLiveController(queryClient, setLive, (text) => setAnnouncement((previous) => (previous === text ? `${text}\u00a0` : text))));

  useEffect(() => () => controller.dispose(), [controller]);

  useEffect(() => {
    if (agents) {
      controller.onAgents(agents);
    }
  }, [controller, agents]);

  // Polled terminal tasks end what a lost task_done left running
  useEffect(() => queryClient.getQueryCache().subscribe((event) => {
    if (event.type === 'updated' && event.action.type === 'success' && event.query.queryKey[0] === QUERY_KEYS.tasks[0]) {
      controller.onTasks(event.query.state.data as TaskInfo[]);
    }
  }), [controller, queryClient]);

  const streamStatus = useEventStream('/api/dashboard/stream', { onEvent: controller.onStreamEvent });

  return { live, streamStatus, announcement };
}

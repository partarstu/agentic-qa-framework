// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { useEffect, useEffectEvent, useState, useSyncExternalStore } from 'react';
import { clearStreamToken, getStreamToken } from '../data/streamToken';

export type StreamStatus = 'connecting' | 'open' | 'reconnecting';

export type StreamEventName = 'snapshot' | 'agent_activity' | 'task_done' | 'log_batch' | 'gap';

const EVENT_NAMES: StreamEventName[] = ['snapshot', 'agent_activity', 'task_done', 'log_batch', 'gap'];

export const RETRY_DELAYS_MS = [1_000, 2_000, 5_000, 10_000, 30_000];

export function usePageVisible(): boolean {
  return useSyncExternalStore((listener) => {
    document.addEventListener('visibilitychange', listener);
    return () => document.removeEventListener('visibilitychange', listener);
  }, () => !document.hidden);
}

interface Handlers {
  onEvent: (name: StreamEventName, data: unknown) => void;
  /** Called on every (re)connect. */
  onOpen?: () => void;
}

/** Keeps an SSE stream open while `url` is set and the page is visible, reconnecting a failed one with a growing delay. */
export function useEventStream(url: string | null, { onEvent, onOpen }: Handlers): StreamStatus {
  const visible = usePageVisible();
  const [status, setStatus] = useState<StreamStatus>('connecting');
  const handleEvent = useEffectEvent(onEvent);
  const handleOpen = useEffectEvent(() => onOpen?.());
  // A hidden tab gives its connection back, since a browser opens at most six per origin over HTTP/1.1
  const active = url !== null && visible;

  useEffect(() => {
    if (!active) {
      return;
    }
    let source: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let stopped = false;

    const retry = () => {
      setStatus('reconnecting');
      retryTimer = setTimeout(() => void connect(), RETRY_DELAYS_MS[Math.min(attempt, RETRY_DELAYS_MS.length - 1)]);
      attempt += 1;
    };

    const connect = async () => {
      let token: string;
      try {
        token = await getStreamToken();
      } catch {
        if (!stopped) {
          retry();
        }
        return;
      }
      if (stopped) {
        return;
      }
      const stream = new EventSource(`${url}?stream_token=${encodeURIComponent(token)}`);
      source = stream;
      stream.onopen = () => {
        attempt = 0;
        setStatus('open');
        handleOpen();
      };
      for (const name of EVENT_NAMES) {
        stream.addEventListener(name, (message) => handleEvent(name, JSON.parse((message as MessageEvent<string>).data)));
      }
      // The stream token expired, not the login: a new one comes from the still valid session, and a rejected session logs out there
      stream.addEventListener('auth_error', () => {
        stream.close();
        clearStreamToken();
        void connect();
      });
      // An error hides whether the orchestrator rejected the token, which a restart forgets, so the retry asks for a new one
      stream.onerror = () => {
        stream.close();
        clearStreamToken();
        retry();
      };
    };

    void connect();
    return () => {
      stopped = true;
      clearTimeout(retryTimer);
      source?.close();
    };
  }, [url, active]);

  return status;
}

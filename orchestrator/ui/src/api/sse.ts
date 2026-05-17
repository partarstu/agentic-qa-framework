import { useEffect, useRef } from 'react';
import { getStreamToken, clearStreamToken } from './streamToken';
import { notifyAuthHandlers } from './client';

export type SseEventType =
  | 'snapshot'
  | 'agent_activity'
  | 'step_result'
  | 'task_done'
  | 'log_batch'
  | 'gap'
  | 'heartbeat';

const SSE_EVENT_TYPES: SseEventType[] = [
  'snapshot', 'agent_activity', 'step_result', 'task_done', 'log_batch', 'gap', 'heartbeat',
];

const MAX_RETRY_DELAY_MS = 30_000;

/**
 * Opens a Server-Sent Events connection to `url` (appending `?stream_token=...`)
 * and calls `onEvent` for each received named-event frame. Reconnects with
 * exponential backoff on network error. Closes permanently on `event: auth-error`.
 *
 * HTTP/1.1 6-conn limit: keep at most one global stream + one per-agent log stream
 * open at any time; close the agent stream when the LogModal closes.
 */
export function useSseEvents(
  url: string,
  onEvent: (type: SseEventType, data: unknown) => void,
): void {
  const onEventRef = useRef(onEvent);
  useEffect(() => {
    onEventRef.current = onEvent;
  });

  useEffect(() => {
    let es: EventSource | null = null;
    let retryDelay = 1_000;
    let cancelled = false;

    async function connect(): Promise<void> {
      if (cancelled) return;
      try {
        const token = await getStreamToken();
        if (cancelled) return;

        const sep = url.includes('?') ? '&' : '?';
        es = new EventSource(`${url}${sep}stream_token=${encodeURIComponent(token)}`);

        es.addEventListener('auth-error', () => {
          clearStreamToken();
          notifyAuthHandlers(false);
          es?.close();
          cancelled = true;
        });

        for (const kind of SSE_EVENT_TYPES) {
          es.addEventListener(kind, (e: MessageEvent) => {
            retryDelay = 1_000;
            if (kind === 'heartbeat') return;
            try {
              onEventRef.current(kind, JSON.parse(e.data));
            } catch {
              /* ignore parse errors */
            }
          });
        }

        es.onerror = () => {
          es?.close();
          es = null;
          if (!cancelled) {
            setTimeout(() => void connect(), retryDelay);
            retryDelay = Math.min(retryDelay * 2, MAX_RETRY_DELAY_MS);
          }
        };
      } catch {
        if (!cancelled) {
          setTimeout(() => void connect(), retryDelay);
          retryDelay = Math.min(retryDelay * 2, MAX_RETRY_DELAY_MS);
        }
      }
    }

    void connect();
    return () => {
      cancelled = true;
      es?.close();
    };
  }, [url]);
}

import { useEffect, useRef } from 'react';
import { getStreamToken, clearStreamToken } from './streamToken';

export type SseEventType =
  | 'snapshot'
  | 'agent_activity'
  | 'task_done'
  | 'log_batch'
  | 'gap'
  | 'heartbeat';

const SSE_EVENT_TYPES: SseEventType[] = [
  'snapshot', 'agent_activity', 'task_done', 'log_batch', 'gap', 'heartbeat',
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
export interface SseOptions {
  enabled?: boolean;
  onOpen?: () => void;
  onClose?: () => void;
}

export function useSseEvents(
  url: string | null,
  onEvent: (type: SseEventType, data: unknown) => void,
  options?: SseOptions,
): void {
  const onEventRef = useRef(onEvent);
  useEffect(() => {
    onEventRef.current = onEvent;
  });

  const enabled = options?.enabled ?? true;
  const onOpenRef = useRef(options?.onOpen);
  const onCloseRef = useRef(options?.onClose);
  useEffect(() => {
    onOpenRef.current = options?.onOpen;
    onCloseRef.current = options?.onClose;
  });

  useEffect(() => {
    if (!url || !enabled) return;
    const streamUrl = url;

    let es: EventSource | null = null;
    let retryDelay = 1_000;
    let cancelled = false;

    async function connect(): Promise<void> {
      if (cancelled) return;
      try {
        const token = await getStreamToken();
        if (cancelled) return;

        const sep = streamUrl.includes('?') ? '&' : '?';
        es = new EventSource(`${streamUrl}${sep}stream_token=${encodeURIComponent(token)}`);

        es.addEventListener('open', () => {
          if (!cancelled && onOpenRef.current) {
            onOpenRef.current();
          }
        });

        es.addEventListener('auth_error', () => {
          // The short-lived stream token expired (not the login session). Clear it and
          // reconnect; the reconnect mints a fresh token from the still-valid JWT. A
          // genuinely expired JWT makes that mint return 401, which the axios response
          // interceptor handles as a real logout — so this must not log the user out.
          clearStreamToken();
          es?.close();
          es = null;
          if (onCloseRef.current) {
            onCloseRef.current();
          }
          if (!cancelled) {
            setTimeout(() => void connect(), retryDelay);
            retryDelay = Math.min(retryDelay * 2, MAX_RETRY_DELAY_MS);
          }
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
          if (onCloseRef.current) {
            onCloseRef.current();
          }
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
      if (onCloseRef.current) {
        onCloseRef.current();
      }
    };
  }, [url, enabled]);
}

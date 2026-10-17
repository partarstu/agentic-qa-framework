// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { useEffect, useEffectEvent, useRef } from 'react';
import { VIEWS, type View } from './views';

export const MOD_KEY = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl';

const SEQUENCE_MILLIS = 1_000;

/** Keys pressed together (`+`) or one after the other (`then`). */
export interface Shortcut {
  keys: string[];
  join: '+' | 'then';
  description: string;
}

export const SHORTCUTS: Shortcut[] = [
  { keys: [MOD_KEY, 'K'], join: '+', description: 'Search and jump' },
  ...VIEWS.map(({ label, key }): Shortcut => ({ keys: ['G', key.toUpperCase()], join: 'then', description: `Go to ${label}` })),
  { keys: ['?'], join: '+', description: 'Show these shortcuts' },
];

/** Whether the key belongs to what the user types, so no shortcut may claim it. */
export function isTypingTarget(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && (target.isContentEditable || target.matches('input, textarea, select'));
}

interface Handlers {
  openPalette: () => void;
  showShortcuts: () => void;
  select: (view: View) => void;
}

/** The dashboard's global keys; they stay out of fields and any open dialog, which keep their keys. */
export function useShortcuts(handlers: Handlers): void {
  const sequenceStartedAt = useRef(Number.NEGATIVE_INFINITY);

  const onKeyDown = useEffectEvent((event: KeyboardEvent) => {
    if (event.defaultPrevented || event.altKey || document.querySelector('dialog[open]')) {
      return;
    }
    if ((event.ctrlKey || event.metaKey) && !event.shiftKey && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      handlers.openPalette();
      return;
    }
    if (event.ctrlKey || event.metaKey || isTypingTarget(event.target)) {
      return;
    }
    const key = event.key.toLowerCase();
    if (event.timeStamp - sequenceStartedAt.current < SEQUENCE_MILLIS) {
      sequenceStartedAt.current = Number.NEGATIVE_INFINITY;
      const view = VIEWS.find((candidate) => candidate.key === key);
      if (view) {
        event.preventDefault();
        handlers.select(view.id);
      }
      return;
    }
    if (key === 'g') {
      sequenceStartedAt.current = event.timeStamp;
    } else if (event.key === '?') {
      event.preventDefault();
      handlers.showShortcuts();
    }
  });

  useEffect(() => {
    const listener = (event: KeyboardEvent) => onKeyDown(event);
    document.addEventListener('keydown', listener);
    return () => document.removeEventListener('keydown', listener);
  }, []);
}

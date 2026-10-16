// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { useSyncExternalStore } from 'react';

export type ThemeChoice = 'system' | 'light' | 'dark';

type Theme = 'light' | 'dark';

const STORAGE_KEY = 'dashboard.theme';

const listeners = new Set<() => void>();
let choice: ThemeChoice = 'system';
let darkQuery: MediaQueryList | null = null;

/** Applies the stored choice and follows the system scheme while the choice is *system*; called once before the first render. */
export function initColorScheme(): void {
  choice = storedChoice();
  darkQuery = matchMedia('(prefers-color-scheme: dark)');
  darkQuery.addEventListener('change', () => {
    if (choice === 'system') {
      apply();
    }
  });
  apply();
}

export function setThemeChoice(next: ThemeChoice): void {
  choice = next;
  try {
    if (next === 'system') {
      localStorage.removeItem(STORAGE_KEY);
    } else {
      localStorage.setItem(STORAGE_KEY, next);
    }
  } catch {
    // Blocked storage only means the choice lasts until the page is reloaded
  }
  apply();
}

export function useThemeChoice(): ThemeChoice {
  return useSyncExternalStore(subscribe, () => choice);
}

function resolvedTheme(): Theme {
  if (choice !== 'system') {
    return choice;
  }
  return darkQuery?.matches ? 'dark' : 'light';
}

function apply() {
  document.documentElement.dataset.theme = resolvedTheme();
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function storedChoice(): ThemeChoice {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === 'light' || stored === 'dark' ? stored : 'system';
  } catch {
    return 'system';
  }
}

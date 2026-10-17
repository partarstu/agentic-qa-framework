// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { initColorScheme, setThemeChoice } from './colorScheme';

function stubSystemScheme(dark: boolean) {
  const listeners: (() => void)[] = [];
  const query = { matches: dark, addEventListener: (_type: string, listener: () => void) => listeners.push(listener) };
  vi.stubGlobal('matchMedia', () => query);
  return (nextDark: boolean) => {
    query.matches = nextDark;
    listeners.forEach((listener) => listener());
  };
}

describe('colour scheme', () => {
  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it('follows the system scheme while the choice is system', () => {
    const changeSystem = stubSystemScheme(true);
    initColorScheme();
    expect(document.documentElement.dataset.theme).toBe('dark');

    changeSystem(false);

    expect(document.documentElement.dataset.theme).toBe('light');
  });

  it('keeps a stored choice over the system scheme and forgets it on system', () => {
    localStorage.setItem('dashboard.theme', 'light');
    const changeSystem = stubSystemScheme(true);
    initColorScheme();
    expect(document.documentElement.dataset.theme).toBe('light');

    changeSystem(true);
    expect(document.documentElement.dataset.theme).toBe('light');

    setThemeChoice('system');
    expect(localStorage.getItem('dashboard.theme')).toBeNull();
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('applies a choice even when the storage is blocked', () => {
    stubSystemScheme(false);
    initColorScheme();
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError');
    });

    setThemeChoice('dark');

    expect(document.documentElement.dataset.theme).toBe('dark');
    vi.restoreAllMocks();
  });
});

// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { vi } from 'vitest';
import { createQueryClient } from '../data/queries';
import { INITIAL_LIVE_STATE, type LiveState } from '../live/liveState';
import { LiveProvider } from '../live/useLiveDashboard';
import { NavigationProvider, type Navigation } from '../navigation';

/**
 * Renders a view or sheet as the shell would, with its own query cache, the given live store and a navigation of spies;
 * `rerender` keeps the cache and may change the navigation.
 */
export function renderView(ui: ReactElement, { navigation = {}, live = INITIAL_LIVE_STATE }: { navigation?: Partial<Navigation>; live?: LiveState } = {}) {
  const spies: Navigation = { openAgent: vi.fn(), openTask: vi.fn(), openLogs: vi.fn(), discover: vi.fn(), sheetOpen: false, ...navigation };
  const queryClient = createQueryClient();
  const wrap = (element: ReactElement, current: Navigation) => (
    <QueryClientProvider client={queryClient}>
      <LiveProvider value={live}>
        <NavigationProvider value={current}>{element}</NavigationProvider>
      </LiveProvider>
    </QueryClientProvider>
  );
  const { rerender } = render(wrap(ui, spies));
  return { navigation: spies, rerender: (element: ReactElement, changes: Partial<Navigation> = {}) => rerender(wrap(element, { ...spies, ...changes })) };
}

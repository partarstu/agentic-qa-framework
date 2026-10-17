// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { createContext, useContext } from 'react';
import type { LogSource } from './data/dashboardApi';

/** What the views ask of the shell: its sheets, the Logs view on a source and the agent discovery. */
export interface Navigation {
  openAgent: (agentId: string) => void;
  openTask: (taskId: string) => void;
  openLogs: (source: LogSource) => void;
  /** Null while a discovery runs. */
  discover: (() => void) | null;
  /** An open sheet owns the per-agent stream, so the Logs view pauses its follow until it closes. */
  sheetOpen: boolean;
  /** The task whose sheet is open, whose row hands its title over to the sheet. */
  openTaskId: string | null;
}

const ignore = () => undefined;

const NavigationContext = createContext<Navigation>({ openAgent: ignore, openTask: ignore, openLogs: ignore, discover: null, sheetOpen: false, openTaskId: null });

export const NavigationProvider = NavigationContext.Provider;

export function useNavigation(): Navigation {
  return useContext(NavigationContext);
}

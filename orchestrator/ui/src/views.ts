// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { Bot, LayoutDashboard, ListChecks, ScrollText, TriangleAlert, type LucideIcon } from 'lucide-react';

export type View = 'overview' | 'agents' | 'tasks' | 'errors' | 'logs';

/** The dashboard's views in tab order, each with the key that follows G to go to it. */
export const VIEWS: { id: View; label: string; Icon: LucideIcon; key: string }[] = [
  { id: 'overview', label: 'Overview', Icon: LayoutDashboard, key: 'o' },
  { id: 'agents', label: 'Agents', Icon: Bot, key: 'a' },
  { id: 'tasks', label: 'Tasks', Icon: ListChecks, key: 't' },
  { id: 'errors', label: 'Errors', Icon: TriangleAlert, key: 'e' },
  { id: 'logs', label: 'Logs', Icon: ScrollText, key: 'l' },
];

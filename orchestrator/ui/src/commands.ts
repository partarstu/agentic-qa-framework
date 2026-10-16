// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { Bot, Keyboard, ListChecks, LogOut, Monitor, Moon, Radar, Sun, type LucideIcon } from 'lucide-react';
import { setThemeChoice } from './colorScheme';
import type { AgentInfo, TaskInfo } from './types/dashboard';
import { VIEWS, type View } from './views';

export interface Command {
  id: string;
  label: string;
  group: string;
  Icon: LucideIcon;
  run: () => void;
}

interface Actions {
  agents: AgentInfo[];
  /** The tasks the palette loaded, or none while they load. */
  tasks: TaskInfo[];
  select: (view: View) => void;
  openAgent: (agentId: string) => void;
  openTask: (taskId: string) => void;
  /** Null while a discovery runs. */
  discover: (() => void) | null;
  showShortcuts: () => void;
  signOut: () => void;
}

/** Everything "Search and jump" offers: the views, every agent and loaded task, the discovery, the theme and the dashboard's own commands. */
export function dashboardCommands({ agents, tasks, select, openAgent, openTask, discover, showShortcuts, signOut }: Actions): Command[] {
  const commands: Command[] = VIEWS.map(({ id, label, Icon }) => ({ id: `view-${id}`, label, group: 'Go to', Icon, run: () => select(id) }));
  commands.push(...agents.map(({ id, name }): Command => ({ id: `agent-${id}`, label: name, group: 'Agent', Icon: Bot, run: () => openAgent(id) })));
  commands.push(...tasks.map(({ task_id, agent_name, description }): Command => ({
    id: `task-${task_id}`, label: description, group: `Task of ${agent_name}`, Icon: ListChecks, run: () => openTask(task_id),
  })));
  if (discover) {
    commands.push({ id: 'discover', label: 'Discover agents', group: 'Agents', Icon: Radar, run: discover });
  }
  commands.push(
    { id: 'theme-light', label: 'Use the light theme', group: 'Theme', Icon: Sun, run: () => setThemeChoice('light') },
    { id: 'theme-dark', label: 'Use the dark theme', group: 'Theme', Icon: Moon, run: () => setThemeChoice('dark') },
    { id: 'theme-system', label: 'Use the system theme', group: 'Theme', Icon: Monitor, run: () => setThemeChoice('system') },
    { id: 'shortcuts', label: 'Keyboard shortcuts', group: 'Dashboard', Icon: Keyboard, run: showShortcuts },
    { id: 'log-out', label: 'Log out', group: 'Dashboard', Icon: LogOut, run: signOut },
  );
  return commands;
}

/** The commands whose label or group contains every word of the query, those whose label starts with it first. */
export function matchCommands(commands: Command[], query: string): Command[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const matches = commands.filter((command) => {
    const text = `${command.label} ${command.group}`.toLowerCase();
    return words.every((word) => text.includes(word));
  });
  const first = words[0];
  if (first === undefined) {
    return matches;
  }
  return [
    ...matches.filter((command) => command.label.toLowerCase().startsWith(first)),
    ...matches.filter((command) => !command.label.toLowerCase().startsWith(first)),
  ];
}

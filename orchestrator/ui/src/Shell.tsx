// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { LoaderCircle, LogOut, Search, WifiOff, X } from 'lucide-react';
import { Activity, startTransition, useState, ViewTransition, type ReactNode } from 'react';
import { CommandPalette } from './CommandPalette';
import { dashboardCommands } from './commands';
import { logout } from './data/authApi';
import { useOrchestratorReachable } from './data/client';
import type { LogSource } from './data/dashboardApi';
import { useAgents, useDiscovery, useTasks } from './data/queries';
import { Aspect, type Tone } from './kit/Aspect';
import { ErrorBoundary } from './kit/ErrorBoundary';
import { IconButton } from './kit/IconButton';
import { QuaiaMark } from './kit/QuaiaMark';
import { TabList, tabPanelProps, type TabItem } from './kit/Tabs';
import { LegalNotice } from './LegalNotice';
import { LiveProvider, useLiveDashboard } from './live/useLiveDashboard';
import type { StreamStatus } from './live/useEventStream';
import { NavigationProvider, type Navigation } from './navigation';
import { PreferencesMenu } from './PreferencesMenu';
import { ShortcutsSheet } from './ShortcutsSheet';
import { MOD_KEY, useShortcuts } from './shortcuts';
import { AgentSheet } from './views/agents/AgentSheet';
import { AgentsView } from './views/agents/AgentsView';
import { ErrorsView } from './views/errors/ErrorsView';
import { LogsView } from './views/logs/LogsView';
import { OverviewView } from './views/overview/OverviewView';
import { TaskSheet } from './views/tasks/TaskSheet';
import { TasksView } from './views/tasks/TasksView';
import { VIEWS, type View } from './views';
import './Shell.css';

const TAB_PREFIX = 'view';
const MAIN_ID = 'dashboard-main';

type OpenSheet = { kind: 'agent' | 'task'; id: string } | null;

const STREAM_ASPECTS: Record<StreamStatus, { tone: Tone; label: string }> = {
  connecting: { tone: 'neutral', label: 'Connecting…' },
  open: { tone: 'passed', label: 'Live' },
  reconnecting: { tone: 'warning', label: 'Reconnecting…' },
};

interface Props {
  onSignedOut: () => void;
}

/** The dashboard around its views: the app bar, "Search and jump", the shortcuts, the live store and the status messages. */
export function Shell({ onSignedOut }: Props) {
  const [view, setView] = useState<View>('overview');
  // A view mounts on its first visit, so the views never opened send no requests
  const [visited, setVisited] = useState<ReadonlySet<View>>(() => new Set(['overview']));
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [sheet, setSheet] = useState<OpenSheet>(null);
  const [logSource, setLogSource] = useState<LogSource>({ kind: 'orchestrator' });
  const agents = useAgents();
  const paletteTasks = useTasks(paletteOpen);
  const discovery = useDiscovery();
  const { live, streamStatus, announcement } = useLiveDashboard(agents.data);
  const reachable = useOrchestratorReachable();

  const select = (next: View) => {
    // A transition, so the views cross-fade
    startTransition(() => {
      setView(next);
      setVisited((previous) => (previous.has(next) ? previous : new Set([...previous, next])));
    });
  };

  const signOut = () => {
    logout();
    onSignedOut();
  };

  const navigation: Navigation = {
    openAgent: (id) => setSheet({ kind: 'agent', id }),
    openTask: (id) => setSheet({ kind: 'task', id }),
    openLogs: (source) => {
      setSheet(null);
      setLogSource(source);
      select('logs');
    },
    discover: discovery.isPending ? null : () => discovery.mutate(),
    sheetOpen: sheet !== null,
  };

  const commands = dashboardCommands({
    agents: agents.data ?? [],
    tasks: paletteOpen ? paletteTasks.data ?? [] : [],
    select,
    openAgent: navigation.openAgent,
    openTask: navigation.openTask,
    discover: navigation.discover,
    showShortcuts: () => setShortcutsOpen(true),
    signOut,
  });

  const viewContent: Record<View, () => ReactNode> = {
    overview: () => <OverviewView />,
    agents: () => <AgentsView />,
    tasks: () => <TasksView />,
    errors: () => <ErrorsView />,
    logs: () => <LogsView source={logSource} onSource={setLogSource} />,
  };

  useShortcuts({ openPalette: () => setPaletteOpen(true), showShortcuts: () => setShortcutsOpen(true), select });

  const tabs: TabItem<View>[] = VIEWS.map(({ id, label, Icon }) => ({ id, label: <><Icon size={18} /><span className="nav-label">{label}</span></> }));
  const stream = STREAM_ASPECTS[streamStatus];

  return (
    <LiveProvider value={live}>
      <NavigationProvider value={navigation}>
        <div className="shell">
          <a className="skip-link" href={`#${MAIN_ID}`}>Skip to the content</a>
          <header className="appbar">
            <div className="appbar-brand">
              <QuaiaMark />
              <h1>QuAIA™ Orchestrator</h1>
            </div>
            <TabList label="Dashboard views" idPrefix={TAB_PREFIX} tabs={tabs} selected={view} onSelect={select} className="appbar-nav" />
            <div className="appbar-tools">
              <span className="appbar-stream">
                <Aspect tone={stream.tone} quiet>
                  <span className="visually-hidden">Updates: </span>
                  {stream.label}
                </Aspect>
              </span>
              <button type="button" className="quiet command-trigger" aria-keyshortcuts="Control+K Meta+K" onClick={() => setPaletteOpen(true)}>
                <Search size={18} />
                <span className="appbar-label">Search and jump</span>
                <kbd className="kbd command-trigger-kbd" aria-hidden="true">{MOD_KEY} K</kbd>
              </button>
              <PreferencesMenu />
              <button type="button" className="quiet" onClick={signOut}>
                <LogOut size={18} />
                <span className="appbar-label">Log out</span>
              </button>
            </div>
          </header>
          <div className="shell-notices">
            <div role="status">
              {!reachable && <p className="note"><WifiOff size={18} />Orchestrator unreachable, retrying</p>}
            </div>
            <div role="status">
              {discovery.isPending && <p className="loading-note"><LoaderCircle size={18} className="spin" />Discovering agents; this can take up to two minutes…</p>}
              {(discovery.isSuccess || discovery.isError) && (
                <p className={discovery.isError ? 'alert' : 'note shell-info'}>
                  <span>{discovery.isError ? `Agent discovery failed: ${discovery.error.message}` : `Agent discovery: ${discovery.data.message}`}</span>
                  <IconButton icon={X} label="Dismiss" small onClick={() => discovery.reset()} />
                </p>
              )}
            </div>
          </div>
          <main id={MAIN_ID} className="shell-main" tabIndex={-1}>
            {VIEWS.filter(({ id }) => visited.has(id)).map(({ id }) => (
              <Activity key={id} mode={view === id ? 'visible' : 'hidden'}>
                <ViewFade>
                  <div {...tabPanelProps(TAB_PREFIX, id)} className="tab-panel">
                    <ErrorBoundary>{viewContent[id]()}</ErrorBoundary>
                  </div>
                </ViewFade>
              </Activity>
            ))}
          </main>
          <LegalNotice />
          <CommandPalette open={paletteOpen} commands={commands} onClose={() => setPaletteOpen(false)} />
          <ShortcutsSheet open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
          <AgentSheet agentId={sheet?.kind === 'agent' ? sheet.id : null} onClose={() => setSheet(null)} />
          <TaskSheet taskId={sheet?.kind === 'task' ? sheet.id : null} onClose={() => setSheet(null)} />
          <div className="visually-hidden" aria-live="polite">{announcement}</div>
        </div>
      </NavigationProvider>
    </LiveProvider>
  );
}

/** Cross-fades a view in and out as the tabs switch, without animating the changes inside it. */
function ViewFade({ children }: { children: ReactNode }) {
  return <ViewTransition default="none" enter="auto" exit="auto">{children}</ViewTransition>;
}

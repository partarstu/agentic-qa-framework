// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { QueryClientProvider } from '@tanstack/react-query';
import { LoaderCircle, Unplug } from 'lucide-react';
import { useEffect, useState } from 'react';
import { probeSession } from './data/authApi';
import { onSessionExpired } from './data/client';
import { createQueryClient } from './data/queries';
import { QuaiaMark } from './kit/QuaiaMark';
import { LegalNotice } from './LegalNotice';
import { LoginView } from './LoginView';
import { Shell } from './Shell';
import './LoginView.css';

type Screen = { kind: 'loading' } | { kind: 'unreachable' } | { kind: 'login'; expired: boolean } | { kind: 'dashboard' };

export function App() {
  const [screen, setScreen] = useState<Screen>({ kind: 'loading' });

  useEffect(() => {
    let active = true;
    void probeSession().then((probe) => {
      if (active) {
        setScreen(probe.kind === 'active' ? { kind: 'dashboard' } : probe.kind === 'none' ? { kind: 'login', expired: false } : { kind: 'unreachable' });
      }
    });
    const stop = onSessionExpired(() => setScreen((current) => (current.kind === 'dashboard' ? { kind: 'login', expired: true } : current)));
    return () => {
      active = false;
      stop();
    };
  }, []);

  switch (screen.kind) {
    case 'loading':
      return (
        <div className="entry">
          <main className="splash" aria-busy="true">
            <h1 className="splash-title"><QuaiaMark />QuAIA™ Orchestrator</h1>
            <p className="loading-note"><LoaderCircle size={18} className="spin" />Connecting to the orchestrator…</p>
          </main>
          <LegalNotice />
        </div>
      );
    case 'unreachable':
      return (
        <div className="entry">
          <main className="splash">
            <h1 className="splash-title"><QuaiaMark />QuAIA™ Orchestrator</h1>
            <div className="empty-state">
              <Unplug size={32} />
              <strong>The orchestrator does not answer</strong>
              <p>Check that it is running, then reload this page.</p>
              <button type="button" className="primary" onClick={() => location.reload()}>Reload</button>
            </div>
          </main>
          <LegalNotice />
        </div>
      );
    case 'login':
      return <LoginView expired={screen.expired} onLoggedIn={() => setScreen({ kind: 'dashboard' })} />;
    case 'dashboard':
      return <Dashboard onSignedOut={() => setScreen({ kind: 'login', expired: false })} />;
  }
}

/** The shell with a query cache of its own, so a new session never sees the data of the last. */
function Dashboard({ onSignedOut }: { onSignedOut: () => void }) {
  const [queryClient] = useState(createQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <Shell onSignedOut={onSignedOut} />
    </QueryClientProvider>
  );
}

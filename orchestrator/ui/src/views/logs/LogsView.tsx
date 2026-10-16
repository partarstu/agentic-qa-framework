// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { useLogTail } from '../../logs/useLogTail';

export function LogsView() {
  const { items, status } = useLogTail({ kind: 'orchestrator' }, { follow: false, level: null });
  return (
    <section className="card">
      <h2>Logs</h2>
      <p>{status === 'ready' ? `${items.length} orchestrator log lines loaded` : status === 'error' ? 'The orchestrator did not answer.' : 'Loading…'}</p>
    </section>
  );
}

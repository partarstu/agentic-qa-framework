// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { useAgents } from '../../data/queries';
import { QueryNote } from '../QueryNote';

export function AgentsView() {
  return (
    <section className="card">
      <h2>Agents</h2>
      <QueryNote query={useAgents()} describe={(agents) => `${agents.length} agents registered`} />
    </section>
  );
}

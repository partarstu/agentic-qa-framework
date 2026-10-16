// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { useSummary } from '../../data/queries';
import { QueryNote } from '../QueryNote';

export function OverviewView() {
  return (
    <section className="card">
      <h2>Overview</h2>
      <QueryNote query={useSummary()} describe={({ tasks_total }) => `${tasks_total} tasks in the history`} />
    </section>
  );
}

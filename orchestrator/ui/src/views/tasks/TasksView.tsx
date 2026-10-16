// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { useTasks } from '../../data/queries';
import { QueryNote } from '../QueryNote';

export function TasksView() {
  return (
    <section className="card">
      <h2>Tasks</h2>
      <QueryNote query={useTasks()} describe={(tasks) => `${tasks.length} of the last 100 tasks loaded`} />
    </section>
  );
}

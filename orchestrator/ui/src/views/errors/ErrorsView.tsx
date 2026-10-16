// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { useErrors } from '../../data/queries';
import { QueryNote } from '../QueryNote';

export function ErrorsView() {
  return (
    <section className="card">
      <h2>Errors</h2>
      <QueryNote query={useErrors()} describe={(errors) => `${errors.length} of the latest 50 errors loaded`} />
    </section>
  );
}

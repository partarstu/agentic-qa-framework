// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import type { UseQueryResult } from '@tanstack/react-query';

/** The state of a view's query in one line, until the view shows its data. */
export function QueryNote<T>({ query, describe }: { query: UseQueryResult<T>; describe: (data: T) => string }) {
  if (query.isPending) {
    return <p className="muted">Loading…</p>;
  }
  if (query.isError) {
    return <p className="alert" role="alert">The orchestrator did not answer: {query.error.message}</p>;
  }
  return <p>{describe(query.data)}</p>;
}

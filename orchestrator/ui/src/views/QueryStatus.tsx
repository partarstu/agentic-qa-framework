// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import type { UseQueryResult } from '@tanstack/react-query';

/** The loading or error state of a view's query in one line; nothing while its data is fresh. */
export function QueryStatus({ query, what }: { query: UseQueryResult<unknown>; what: string }) {
  if (query.isPending) {
    return <p className="muted">Loading {what}…</p>;
  }
  if (query.isError) {
    return <p className="alert" role="alert">The orchestrator did not answer: {query.error.message}</p>;
  }
  return null;
}

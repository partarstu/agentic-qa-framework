// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError } from './client';
import { getAgents, getErrors, getRagSyncStatus, getSummary, getTasks, triggerDiscovery } from './dashboardApi';

export const QUERY_KEYS = {
  agents: ['agents'],
  summary: ['summary'],
  tasks: ['tasks'],
  errors: ['errors'],
  ragSync: ['rag-sync-status'],
} as const;

export type QueryName = keyof typeof QUERY_KEYS;

const AGENTS_POLL_MS = 3_000;
// The stream invalidates the views' queries; polling only catches what no event announces
const FALLBACK_POLL_MS = 10_000;
// Every call reads Qdrant
const RAG_SYNC_POLL_MS = 60_000;

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // A client error repeats on a retry; a server or network error may not
        retry: (failures, error) => failures < 1 && !(error instanceof ApiError && error.status < 500),
        refetchInterval: FALLBACK_POLL_MS,
      },
    },
  });
}

/** The agents query the shell owns: it feeds the topology, the agent meter and the palette, and catches task starts no event announced. */
export const useAgents = () =>
  useQuery({ queryKey: QUERY_KEYS.agents, queryFn: ({ signal }) => getAgents(signal), refetchInterval: AGENTS_POLL_MS });

export const useSummary = () => useQuery({ queryKey: QUERY_KEYS.summary, queryFn: ({ signal }) => getSummary(signal) });

export const useTasks = (enabled = true) => useQuery({ queryKey: QUERY_KEYS.tasks, queryFn: ({ signal }) => getTasks(signal), enabled });

export const useErrors = () => useQuery({ queryKey: QUERY_KEYS.errors, queryFn: ({ signal }) => getErrors(signal) });

export const useRagSyncStatus = () =>
  useQuery({ queryKey: QUERY_KEYS.ragSync, queryFn: ({ signal }) => getRagSyncStatus(signal), refetchInterval: RAG_SYNC_POLL_MS });

/** The manual agent discovery; it re-probes every agent, so the agents query refreshes after it. */
export function useDiscovery() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: triggerDiscovery,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QUERY_KEYS.agents }),
  });
}

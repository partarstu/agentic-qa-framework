// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import DOMPurify from 'dompurify';

/** An agent card's description, which may carry HTML lists. */
export function AgentDescription({ html, clamped = false }: { html: string; clamped?: boolean }) {
  const className = clamped ? 'agent-description agent-description-clamped' : 'agent-description';
  return (
    // eslint-disable-next-line no-restricted-syntax -- the one HTML sink: DOMPurify strips scripts, event handlers and unsafe URLs first
    <div className={className} dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html, { RETURN_TRUSTED_TYPE: true }) }} />
  );
}

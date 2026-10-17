// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import './QuaiaMark.css';

/** The QuAIA mark: a shield of linked agents with a check across it, drawn in the theme's accent and passed colours. */
export function QuaiaMark({ size = 28 }: { size?: number }) {
  return (
    <svg className="quaia-mark" viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
      <path className="quaia-mark-shield" d="M12 1.75C15.2 1.75 18.2 2.6 20.6 4.1V11C20.6 16 17.2 19.9 12 22.25C6.8 19.9 3.4 16 3.4 11V4.1C5.8 2.6 8.8 1.75 12 1.75Z" />
      <path className="quaia-mark-links" d="M12 1.75L9.6 6.6L6.6 9.4L7.4 15.4L12 22.25M9.6 6.6L13.2 7.4L17 5.4M6.6 9.4L3.4 11M17.4 10.6L16.3 15.6L12 22.25M17.4 10.6L20.6 11" />
      <g className="quaia-mark-nodes">
        <circle cx="12" cy="1.75" r="1.3" />
        <circle cx="9.6" cy="6.6" r="1.2" />
        <circle cx="17" cy="5.4" r="1.1" />
        <circle cx="6.6" cy="9.4" r="1.1" />
        <circle cx="17.4" cy="10.6" r="1.1" />
        <circle cx="7.4" cy="15.4" r="1" />
        <circle cx="16.3" cy="15.6" r="1" />
        <circle cx="12" cy="22.25" r="1.3" />
      </g>
      <path className="quaia-mark-check" d="M7.6 11.2L11 14.6L19.8 4.6" />
    </svg>
  );
}

// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

export interface TrackPart {
  key: string;
  value: number;
  className: string;
}

/** The bar of a part-to-whole chart, hidden from assistive technology: the chart's legend carries the same figures as text. */
export function BarTrack({ parts }: { parts: TrackPart[] }) {
  return (
    <span className="bar-track" aria-hidden="true">
      {parts.filter(({ value }) => value > 0).map(({ key, value, className }) => (
        <span key={key} className={`bar-part ${className}`} style={{ flexGrow: value }} />
      ))}
    </span>
  );
}

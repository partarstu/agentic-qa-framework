// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import './charts.css';

const WIDTH = 100;
const HEIGHT = 24;
const PADDING = 2;

interface Props {
  /** What the line shows; with the values, it is the line's text alternative. */
  label: string;
  /** Oldest first. */
  values: number[];
  max: number;
  format: (value: number) => string;
}

/** A trend as a small line, named by its label and every value it draws. */
export function Sparkline({ label, values, max, format }: Props) {
  if (values.length === 0) {
    return <span className="sparkline-empty muted">No data yet</span>;
  }
  const x = (index: number) => (index / (values.length - 1)) * WIDTH;
  const y = (value: number) => PADDING + (1 - (max > 0 ? Math.min(Math.max(value, 0), max) / max : 0)) * (HEIGHT - 2 * PADDING);
  const points = values.length === 1 ? [[0, y(values[0])], [WIDTH, y(values[0])]] : values.map((value, index) => [x(index), y(value)]);
  const line = points.map(([px, py]) => `${px},${py}`).join(' ');
  return (
    <svg className="sparkline" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none" role="img"
      aria-label={`${label}: ${values.map(format).join(', ')}`}>
      <polygon className="sparkline-area" points={`0,${HEIGHT} ${line} ${WIDTH},${HEIGHT}`} />
      <polyline className="sparkline-line" points={line} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { percent } from '../format';
import { BarTrack } from './BarTrack';
import './charts.css';

export interface BarPart {
  label: string;
  value: number;
}

/** The series colours tell four parts apart for colour-blind eyes too, so smaller parts beyond three fold into "Other". */
const SERIES_COUNT = 4;

export function foldParts(parts: BarPart[]): BarPart[] {
  const sorted = parts.filter(({ value }) => value > 0).toSorted((first, second) => second.value - first.value);
  if (sorted.length <= SERIES_COUNT) {
    return sorted;
  }
  const rest = sorted.slice(SERIES_COUNT - 1).reduce((sum, { value }) => sum + value, 0);
  return [...sorted.slice(0, SERIES_COUNT - 1), { label: 'Other', value: rest }];
}

/** Parts of a whole as one bar in the series colours, with a legend of names, figures and shares that is its text alternative. */
export function StackedBar({ label, parts, format }: { label: string; parts: BarPart[]; format: (value: number) => string }) {
  const folded = foldParts(parts);
  const total = folded.reduce((sum, { value }) => sum + value, 0);
  if (total === 0) {
    return <p className="empty">Nothing recorded.</p>;
  }
  return (
    <div className="stacked-bar">
      <BarTrack parts={folded.map(({ label: part, value }, index) => ({ key: part, value, className: `bar-series-${index + 1}` }))} />
      <ul className="chart-legend" aria-label={label}>
        {folded.map(({ label: part, value }, index) => (
          <li key={part}>
            <span className={`chart-swatch bar-series-${index + 1}`} aria-hidden="true" />
            {part}: {format(value)} ({percent(value / total)})
          </li>
        ))}
      </ul>
    </div>
  );
}

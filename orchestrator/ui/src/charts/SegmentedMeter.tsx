// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { Aspect, type Tone } from '../kit/Aspect';
import { BarTrack } from './BarTrack';
import './charts.css';

export interface MeterSegment {
  label: string;
  value: number;
  tone: Tone;
}

/** Counts by status as one bar, with a legend of aspects (colour, shape and word) that is its text alternative. */
export function SegmentedMeter({ label, segments }: { label: string; segments: MeterSegment[] }) {
  const shown = segments.filter(({ value }) => value > 0);
  return (
    <div className="segmented-meter">
      <BarTrack parts={shown.map(({ label: part, value, tone }) => ({ key: part, value, className: `bar-tone-${tone}` }))} />
      <ul className="chart-legend" aria-label={label}>
        {shown.length === 0
          ? <li className="muted">None</li>
          : shown.map(({ label: part, value, tone }) => (
            <li key={part}><Aspect tone={tone} quiet>{value} {part}</Aspect></li>
          ))}
      </ul>
    </div>
  );
}

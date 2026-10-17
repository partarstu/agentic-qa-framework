// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import './Meter.css';

export type MeterTone = 'good' | 'fair' | 'poor';

interface Props {
  label: string;
  value: number;
  max: number;
  valueText: string;
  /** A quantity that is neither good nor bad, such as busy capacity, fills in the accent instead of a status colour. */
  neutral?: boolean;
}

const GOOD_PERCENT = 80;
const FAIR_PERCENT = 50;

/** The tone of a ratio where more is better, which the bar shows in the status colours next to the number that carries it. */
export function meterTone(percent: number): MeterTone {
  if (percent >= GOOD_PERCENT) {
    return 'good';
  }
  return percent >= FAIR_PERCENT ? 'fair' : 'poor';
}

/** A ratio as a thin bar, announced with its own wording; the caller shows the same wording as text. */
export function Meter({ label, value, max, valueText, neutral = false }: Props) {
  const percent = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  return (
    <span className={`meter meter-${neutral ? 'neutral' : meterTone(percent)}`} role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={max}
      aria-valuenow={value} aria-valuetext={valueText}>
      <span className="meter-fill" style={{ inlineSize: `${percent}%` }} />
    </span>
  );
}

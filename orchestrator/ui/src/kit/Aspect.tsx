// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { CircleCheck, CircleDashed, OctagonAlert, SquareX, TriangleAlert, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import './Aspect.css';

export type Tone = 'passed' | 'failed' | 'warning' | 'error' | 'running' | 'neutral';

const SHAPES: Record<Exclude<Tone, 'running'>, LucideIcon> = {
  passed: CircleCheck,
  failed: SquareX,
  warning: TriangleAlert,
  error: OctagonAlert,
  neutral: CircleDashed,
};

/** A status as a signal aspect: a colour, a shape of its own and a word, so it never depends on colour alone. */
export function Aspect({ tone, children, quiet = false }: { tone: Tone; children: ReactNode; quiet?: boolean }) {
  const Shape = tone === 'running' ? null : SHAPES[tone];
  return (
    <span className={`aspect aspect-${tone}${quiet ? ' aspect-quiet' : ''}`}>
      {Shape ? <Shape size={14} strokeWidth={2.25} /> : <span className="aspect-pulse" aria-hidden="true" />}
      {children}
    </span>
  );
}

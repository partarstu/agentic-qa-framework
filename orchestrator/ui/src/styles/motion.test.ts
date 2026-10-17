// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { describe, expect, it } from 'vitest';

const sheets = import.meta.glob<string>('../**/*.css', { query: '?raw', import: 'default', eager: true });

const MOTION_GATE = 'prefers-reduced-motion: no-preference';
const MOVING_TRANSITION = /translate|rotate|scale|transform/;

interface Declaration {
  sheet: string;
  property: string;
  value: string;
  gated: boolean;
}

/** The declarations of a nested stylesheet, each with whether a block around it lets motion through only without reduced motion. */
function declarations(sheet: string, css: string): Declaration[] {
  const found: Declaration[] = [];
  const preludes: string[] = [];
  let text = '';
  for (const character of css.replace(/\/\*[\s\S]*?\*\//g, '')) {
    if (character === '{') {
      preludes.push(text.trim());
      text = '';
    } else if (character === ';' || character === '}') {
      const match = /^([\w-]+)\s*:\s*([\s\S]+)$/.exec(text.trim());
      if (match) {
        found.push({ sheet, property: match[1], value: match[2], gated: preludes.some((prelude) => prelude.includes(MOTION_GATE)) });
      }
      text = '';
      if (character === '}') {
        preludes.pop();
      }
    } else {
      text += character;
    }
  }
  return found;
}

const all = Object.entries(sheets).flatMap(([path, css]) => declarations(path, css));

describe('motion', () => {
  it('reads the stylesheets', () => {
    expect(all.some(({ property }) => property === 'animation')).toBe(true);
  });

  it('runs every animation only without reduced motion', () => {
    const ungated = all.filter(({ property, value, gated }) => property === 'animation' && value !== 'none' && !gated);

    expect(ungated).toEqual([]);
  });

  it('moves nothing by a transition under reduced motion', () => {
    const ungated = all.filter(({ property, value, gated }) => property === 'transition' && MOVING_TRANSITION.test(value) && !gated);

    expect(ungated).toEqual([]);
  });
});

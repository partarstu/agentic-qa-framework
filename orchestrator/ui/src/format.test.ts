// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { describe, expect, it } from 'vitest';
import { age, compactCount, duration, percent, usd } from './format';

// The runner's locale picks the words and the decimal separator, so the checks look at the numbers only
describe('duration', () => {
  it('keeps milliseconds below a second', () => {
    expect(duration(850)).toMatch(/^850\D/);
  });

  it('shows one decimal below a minute', () => {
    expect(duration(2_310)).toMatch(/^2[.,]3\D/);
  });

  it('shows whole minutes and seconds above a minute', () => {
    expect(duration(65_400)).toMatch(/^1\D+5\D/);
    expect(duration(65_400)).not.toMatch(/[.,]\d/);
  });

  it('never goes below zero', () => {
    expect(duration(-5)).toMatch(/^0\D/);
  });
});

describe('age', () => {
  const now = Date.parse('2026-10-04T12:00:00Z');

  it('counts days beyond a day', () => {
    expect(age('2026-10-01T12:00:00Z', now)).toMatch(/3/);
  });

  it('counts minutes within the hour', () => {
    expect(age('2026-10-04T11:55:00Z', now)).toMatch(/5/);
  });
});

describe('figures', () => {
  it('shortens a large count', () => {
    expect(compactCount(1_234_000)).toMatch(/^1[.,]2/);
  });

  it('keeps the fractions of a cent in a cost', () => {
    expect(usd(0.0042)).toMatch(/0[.,]0042/);
  });

  it('rounds a ratio to a whole percentage', () => {
    expect(percent(0.924)).toMatch(/^92\D|\D92\D/);
  });
});

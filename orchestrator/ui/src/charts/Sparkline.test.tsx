// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { axeViolations, installDom } from '../testing/dom';
import { Sparkline } from './Sparkline';

installDom();

const format = (value: number) => `${value} %`;

describe('Sparkline', () => {
  it('draws the values oldest first, top for the maximum, and names each in its text alternative', async () => {
    render(<Sparkline label="Success rate, last 100 tasks" values={[100, 50, 0]} max={100} format={format} />);

    expect(screen.getByRole('img', { name: 'Success rate, last 100 tasks: 100 %, 50 %, 0 %' })).toBeTruthy();
    expect(document.querySelector('polyline')?.getAttribute('points')).toBe('0,2 50,12 100,22');
    expect(await axeViolations()).toEqual([]);
  });

  it('draws a single value as a flat line', () => {
    render(<Sparkline label="Success rate" values={[100]} max={100} format={format} />);

    expect(document.querySelector('polyline')?.getAttribute('points')).toBe('0,2 100,2');
  });

  it('says that there is no data yet without values', async () => {
    render(<Sparkline label="Success rate" values={[]} max={100} format={format} />);

    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.getByText('No data yet')).toBeTruthy();
    expect(await axeViolations()).toEqual([]);
  });
});

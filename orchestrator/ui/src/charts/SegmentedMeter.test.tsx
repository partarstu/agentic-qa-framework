// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { axeViolations, installDom } from '../testing/dom';
import { SegmentedMeter } from './SegmentedMeter';

installDom();

describe('SegmentedMeter', () => {
  it('draws a part per status in proportion and names every count in its legend', async () => {
    render(<SegmentedMeter label="Agents by status" segments={[
      { label: 'available', value: 4, tone: 'passed' }, { label: 'busy', value: 2, tone: 'running' }, { label: 'broken', value: 0, tone: 'failed' },
    ]} />);

    const legend = screen.getByRole('list', { name: 'Agents by status' });
    expect([...legend.querySelectorAll('li')].map((item) => item.textContent)).toEqual(['4 available', '2 busy']);
    expect([...document.querySelectorAll<HTMLElement>('.bar-part')].map((part) => part.style.flexGrow)).toEqual(['4', '2']);
    expect(document.querySelector('.bar-track')?.getAttribute('aria-hidden')).toBe('true');
    expect(await axeViolations()).toEqual([]);
  });

  it('says None without counts', async () => {
    render(<SegmentedMeter label="Agents by status" segments={[{ label: 'available', value: 0, tone: 'passed' }]} />);

    expect(screen.getByRole('list', { name: 'Agents by status' }).textContent).toBe('None');
    expect(document.querySelectorAll('.bar-part')).toHaveLength(0);
    expect(await axeViolations()).toEqual([]);
  });
});

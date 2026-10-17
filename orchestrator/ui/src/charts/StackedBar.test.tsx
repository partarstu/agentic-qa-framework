// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { axeViolations, installDom } from '../testing/dom';
import { foldParts, StackedBar } from './StackedBar';

installDom();

const format = (value: number) => `${value} tokens`;

describe('StackedBar', () => {
  it('names every part with its figure and share, largest first', async () => {
    render(<StackedBar label="Tokens by operation" format={format} parts={[{ label: 'classifier', value: 250 }, { label: 'main', value: 750 }]} />);

    const legend = screen.getByRole('list', { name: 'Tokens by operation' });
    expect([...legend.querySelectorAll('li')].map((item) => item.textContent?.replace(/\s/g, ' '))).toEqual([
      expect.stringMatching(/^main: 750 tokens \(75 ?%\)$/), expect.stringMatching(/^classifier: 250 tokens \(25 ?%\)$/),
    ]);
    expect([...document.querySelectorAll<HTMLElement>('.bar-part')].map((part) => part.style.flexGrow)).toEqual(['750', '250']);
    expect(await axeViolations()).toEqual([]);
  });

  it('folds the parts beyond three into Other, since four series colours are all colour-blind eyes tell apart', () => {
    const folded = foldParts([1, 2, 3, 4, 5].map((value) => ({ label: `op-${value}`, value })));

    expect(folded).toEqual([{ label: 'op-5', value: 5 }, { label: 'op-4', value: 4 }, { label: 'op-3', value: 3 }, { label: 'Other', value: 3 }]);
  });

  it('says that nothing was recorded without parts', async () => {
    render(<StackedBar label="Tokens by operation" format={format} parts={[{ label: 'main', value: 0 }]} />);

    expect(screen.getByText('Nothing recorded.')).toBeTruthy();
    expect(await axeViolations()).toEqual([]);
  });
});

// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { act, fireEvent, render, screen } from '@testing-library/react';
import { Search } from 'lucide-react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { axeViolations, installDom } from '../testing/dom';
import { IconButton } from './IconButton';
import { useTooltip } from './Tooltip';

installDom();

function DescribedButton() {
  const { trigger, tooltip } = useTooltip('Opens the agent sheet');
  return (
    <>
      <button type="button" {...trigger}>Requirements review</button>
      {tooltip}
    </>
  );
}

// jsdom hides a popover even once the stub has shown it, so the tooltip is found by its role attribute
const tooltip = () => document.querySelector<HTMLElement>('[role="tooltip"]')!;

const shown = () => tooltip().hasAttribute('data-popover-open');

const waitPastDelay = () => act(() => vi.advanceTimersByTime(500));

describe('tooltips', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows the label of an icon button on keyboard focus and keeps it as the accessible name only', async () => {
    render(<IconButton icon={Search} label="Search" />);
    const button = screen.getByRole('button', { name: 'Search' });

    fireEvent.focus(button);
    await waitPastDelay();

    expect(shown()).toBe(true);
    expect(tooltip().textContent).toBe('Search');
    expect(button.getAttribute('aria-describedby')).toBeNull();
    expect(button.hasAttribute('title')).toBe(false);
    vi.useRealTimers();
    expect(await axeViolations()).toEqual([]);
  });

  it('hides on Escape without the key reaching the page', async () => {
    const onPageKey = vi.fn();
    document.addEventListener('keydown', onPageKey);
    render(<IconButton icon={Search} label="Search" />);
    const button = screen.getByRole('button', { name: 'Search' });
    fireEvent.focus(button);
    await waitPastDelay();

    fireEvent.keyDown(button, { key: 'Escape' });

    expect(shown()).toBe(false);
    expect(onPageKey).not.toHaveBeenCalled();
    document.removeEventListener('keydown', onPageKey);
  });

  it('shows on hover, stays while the pointer moves onto it and hides once the pointer leaves both', async () => {
    render(<IconButton icon={Search} label="Search" />);
    const button = screen.getByRole('button', { name: 'Search' });

    fireEvent.pointerEnter(button);
    await waitPastDelay();
    expect(shown()).toBe(true);

    fireEvent.pointerLeave(button);
    fireEvent.pointerEnter(tooltip());
    await waitPastDelay();
    expect(shown()).toBe(true);

    fireEvent.pointerLeave(tooltip());
    await waitPastDelay();
    expect(shown()).toBe(false);
  });

  it('stays hidden when a click focuses the button', async () => {
    render(<IconButton icon={Search} label="Search" />);
    const button = screen.getByRole('button', { name: 'Search' });

    fireEvent.pointerDown(button);
    fireEvent.focus(button);
    await waitPastDelay();

    expect(shown()).toBe(false);
  });

  it('describes what a named button does instead of the native title', () => {
    render(<DescribedButton />);
    const button = screen.getByRole('button', { name: 'Requirements review' });

    expect(button.hasAttribute('title')).toBe(false);
    expect(document.getElementById(button.getAttribute('aria-describedby') ?? '')?.textContent).toBe('Opens the agent sheet');
  });
});

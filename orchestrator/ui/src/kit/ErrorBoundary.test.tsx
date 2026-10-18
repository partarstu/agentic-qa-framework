// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { axeViolations, installDom } from '../testing/dom';
import { ErrorBoundary } from './ErrorBoundary';

installDom();

let failing = true;

function FragileView() {
  if (failing) {
    throw new Error('Unexpected shape');
  }
  return <p>The view</p>;
}

function renderPanels() {
  failing = true;
  // React logs a caught render error; the test expects the error, so the log is silenced
  vi.spyOn(console, 'error').mockImplementation(() => {});
  render(
    <>
      <div><ErrorBoundary><FragileView /></ErrorBoundary></div>
      <div><ErrorBoundary><p>The open sheet</p></ErrorBoundary></div>
    </>,
  );
}

describe('ErrorBoundary', () => {
  it('shows the failure in place of the failing view while a sibling view stays rendered', async () => {
    renderPanels();

    expect(screen.getByRole('alert').textContent).toContain('This view failed');
    expect(screen.getByText('The open sheet')).toBeTruthy();
    expect(await axeViolations()).toEqual([]);
  });

  it('mounts the view afresh when the user shows it again', () => {
    renderPanels();
    failing = false;

    fireEvent.click(screen.getByRole('button', { name: 'Show it again' }));

    expect(screen.getByText('The view')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

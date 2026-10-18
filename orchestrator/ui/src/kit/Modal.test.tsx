// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { axeViolations, installDom } from '../testing/dom';
import { Modal } from './Modal';

installDom();

const dialog = () => document.querySelector('dialog')!;

describe('Modal', () => {
  it('opens as a dialog named by its title and moves the focus to the marked control', async () => {
    render(
      <Modal open title="Task details" onCancel={vi.fn()}>
        <button type="button">Copy</button>
        <button type="button" data-autofocus>Close</button>
      </Modal>,
    );

    expect(dialog().open).toBe(true);
    expect(screen.getByRole('dialog', { name: 'Task details' })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Close' }));
    expect(await axeViolations()).toEqual([]);
  });

  it('gives the safe answer on Escape and closes when no longer open', () => {
    const onCancel = vi.fn();
    const { rerender } = render(<Modal open title="Task details" onCancel={onCancel}><p>Body</p></Modal>);

    fireEvent(dialog(), new Event('cancel', { cancelable: true }));
    expect(onCancel).toHaveBeenCalledOnce();
    expect(dialog().open).toBe(true);

    rerender(<Modal open={false} title="Task details" onCancel={onCancel}><p>Body</p></Modal>);
    expect(dialog().open).toBe(false);
  });

  it('shows itself again when the browser closes it without an answer', () => {
    const onCancel = vi.fn();
    render(<Modal open title="Task details" onCancel={onCancel}><p>Body</p></Modal>);

    dialog().open = false;
    fireEvent(dialog(), new Event('close'));

    expect(dialog().open).toBe(true);
    expect(onCancel).toHaveBeenCalledOnce();
  });
});

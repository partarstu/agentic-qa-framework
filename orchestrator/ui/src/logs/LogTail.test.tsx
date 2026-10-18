// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { COPY_BLOCKED } from '../clipboard';
import { axeViolations, installDom } from '../testing/dom';
import { logEntry } from '../testing/fixtures';
import { LogTail, type LogTailState } from './LogTail';
import type { TailItem } from './tailItems';

installDom();

const entry = (id: string, message: string, level = 'INFO'): TailItem => ({ kind: 'entry', entry: logEntry({ id, message, level, timestamp: '' }) });

const ITEMS: TailItem[] = [
  entry('task-1:3', 'Save failed', 'ERROR'),
  { kind: 'missed', key: 'missed-1' },
  entry('task-1:2', 'Retrying the save', 'WARNING'),
  entry('task-1:1', 'Reading the story'),
];

function tail(overrides: Partial<LogTailState> = {}): LogTailState {
  return { items: ITEMS, status: 'ready', loadingOlder: false, olderFailed: false, exhausted: false, taskDone: false, loadOlder: vi.fn(), ...overrides };
}

const region = () => screen.getByRole('region', { name: 'Task logs' });

describe('LogTail', () => {
  it('shows the newest line on top in a focusable region that never announces streamed lines, with the markers in place', async () => {
    render(<LogTail title="Task logs" tail={tail()} />);

    expect(region().getAttribute('tabindex')).toBe('0');
    expect(region().getAttribute('aria-live')).toBeNull();
    expect([...region().children].map((line) => line.textContent)).toEqual([
      'ERROR agent.requirements - Save failed', 'Events missed here', 'WARNING agent.requirements - Retrying the save',
      'INFO agent.requirements - Reading the story',
    ]);
    expect(region().querySelector('.log-error')).toBeTruthy();
    expect(region().querySelector('.log-warn')).toBeTruthy();
    expect(screen.getByText('3 loaded lines')).toBeTruthy();
    expect(await axeViolations()).toEqual([]);
  });

  it('labels each line with its task where the tail mixes several', () => {
    render(<LogTail title="Task logs" tail={tail({ items: [entry('task-1:1', 'Reading the story')] })} taskLabel={(taskId) => `Review ${taskId}`} />);

    expect(region().textContent).toBe('INFO [Review task-1] agent.requirements - Reading the story');
  });

  it('keeps the place of a reader who scrolled down and offers to jump to the newest', () => {
    const { rerender } = render(<LogTail title="Task logs" tail={tail()} />);
    region().scrollTop = 100;
    fireEvent.scroll(region());

    rerender(<LogTail title="Task logs" tail={tail({ items: [entry('task-1:4', 'Done'), ...ITEMS] })} />);
    expect(region().scrollTop).toBe(100);

    fireEvent.click(screen.getByRole('button', { name: 'Jump to the newest' }));
    expect(region().scrollTop).toBe(0);
  });

  it('filters the loaded lines by text, marks the matches and leaves out the markers', () => {
    render(<LogTail title="Task logs" tail={tail()} />);

    fireEvent.change(screen.getByRole('searchbox', { name: 'Find in the loaded lines' }), { target: { value: 'save' } });

    expect([...document.querySelectorAll('mark')].map((mark) => mark.textContent)).toEqual(['Save', 'save']);
    expect(screen.getByText('2 of 3 loaded lines')).toBeTruthy();
    expect(screen.queryByText('Events missed here')).toBeNull();
  });

  it('says so when no loaded line matches', () => {
    render(<LogTail title="Task logs" tail={tail()} />);

    fireEvent.change(screen.getByRole('searchbox', { name: 'Find in the loaded lines' }), { target: { value: 'nothing' } });

    expect(screen.getByText('No loaded line matches.')).toBeTruthy();
  });

  it('copies the lines shown oldest first, as a log is read elsewhere', async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    render(<LogTail title="Task logs" tail={tail()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Copy the loaded lines' }));

    expect((await screen.findByRole('status')).textContent).toBe('Copied');
    expect(writeText).toHaveBeenCalledWith(
      'INFO agent.requirements - Reading the story\nWARNING agent.requirements - Retrying the save\nERROR agent.requirements - Save failed',
    );
  });

  it('says that the browser blocked copying when the Clipboard API is missing', async () => {
    vi.stubGlobal('navigator', {});
    render(<LogTail title="Task logs" tail={tail()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Copy the loaded lines' }));

    expect((await screen.findByText(COPY_BLOCKED)).getAttribute('role')).toBe('status');
  });

  it('loads older lines on request and says when the oldest is loaded', () => {
    const loadOlder = vi.fn();
    const { rerender } = render(<LogTail title="Task logs" tail={tail({ loadOlder })} />);

    fireEvent.click(screen.getByRole('button', { name: 'Load older lines' }));
    expect(loadOlder).toHaveBeenCalledOnce();

    rerender(<LogTail title="Task logs" tail={tail({ exhausted: true })} />);
    expect(screen.queryByRole('button', { name: 'Load older lines' })).toBeNull();
    expect(screen.getByText('The oldest line is loaded.')).toBeTruthy();
  });

  it('shows the loading, empty and error states', () => {
    const { rerender } = render(<LogTail title="Task logs" tail={tail({ status: 'loading', items: [] })} />);
    expect(screen.getByText('Loading the log…')).toBeTruthy();

    rerender(<LogTail title="Task logs" tail={tail({ items: [] })} />);
    expect(screen.getByText('No log lines yet.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Load older lines' })).toBeNull();

    rerender(<LogTail title="Task logs" tail={tail({ status: 'error', items: [] })} />);
    expect(screen.getByRole('alert').textContent).toContain('The log could not be loaded');
  });
});

// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { axeViolations, installDom } from '../testing/dom';
import { TabList, tabPanelProps } from './Tabs';

installDom();

const TABS = [{ id: 'overview', label: 'Overview' }, { id: 'agents', label: 'Agents' }, { id: 'tasks', label: 'Tasks' }];

function renderTabs(onSelect = vi.fn()) {
  render(
    <>
      <TabList label="Dashboard views" idPrefix="view" tabs={TABS} selected="overview" onSelect={onSelect} />
      <div {...tabPanelProps('view', 'overview')}>Overview content</div>
    </>,
  );
  return onSelect;
}

describe('TabList', () => {
  it('moves the focus with the arrows, Home and End without selecting', () => {
    const onSelect = renderTabs();
    const [overview, agents, tasks] = screen.getAllByRole('tab');
    overview.focus();

    fireEvent.keyDown(overview, { key: 'ArrowRight' });
    expect(document.activeElement).toBe(agents);
    fireEvent.keyDown(agents, { key: 'End' });
    expect(document.activeElement).toBe(tasks);
    fireEvent.keyDown(tasks, { key: 'ArrowRight' });
    expect(document.activeElement).toBe(overview);
    fireEvent.keyDown(overview, { key: 'ArrowLeft' });
    expect(document.activeElement).toBe(tasks);
    fireEvent.keyDown(tasks, { key: 'Home' });
    expect(document.activeElement).toBe(overview);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('selects a tab when it is activated', () => {
    const onSelect = renderTabs();

    fireEvent.click(screen.getByRole('tab', { name: 'Agents' }));

    expect(onSelect).toHaveBeenCalledWith('agents');
  });

  it('keeps only the selected tab in the tab order and ties it to its panel', async () => {
    renderTabs();

    expect(screen.getAllByRole('tab').map((tab) => tab.tabIndex)).toEqual([0, -1, -1]);
    expect(screen.getByRole('tabpanel', { name: 'Overview' }).textContent).toBe('Overview content');
    expect(await axeViolations()).toEqual([]);
  });
});

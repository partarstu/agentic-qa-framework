// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

const START = '[data-autofocus], h3, input:not([type="hidden"]), textarea, select, button';

/**
 * Moves the focus to the start of a view that replaced the focused one, unless a control of the view already took it on mount;
 * a heading becomes focusable for this only.
 */
export function focusViewStart(view: Element | null | undefined): void {
  if (!view || view.contains(document.activeElement)) {
    return;
  }
  const start = view.querySelector<HTMLElement>(START);
  if (start?.tagName === 'H3') {
    start.tabIndex = -1;
  }
  start?.focus();
}

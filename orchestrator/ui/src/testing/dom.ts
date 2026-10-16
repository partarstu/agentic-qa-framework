// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { cleanup } from '@testing-library/react';
import axe from 'axe-core';
import { afterEach, beforeEach, vi } from 'vitest';

/** Gives jsdom the dialog and popover methods, scrollIntoView, matchMedia and ResizeObserver the dashboard uses, and unmounts every render after its test. */
export function installDom(): void {
  if (typeof HTMLDialogElement.prototype.showModal !== 'function') {
    HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
      this.open = true;
    };
    HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
      this.open = false;
    };
  }
  // The stubs mark a shown popover with data-popover-open, which jsdom cannot match as :popover-open
  if (typeof HTMLElement.prototype.showPopover !== 'function') {
    HTMLElement.prototype.showPopover = function showPopover(this: HTMLElement) {
      this.toggleAttribute('data-popover-open', true);
    };
    HTMLElement.prototype.hidePopover = function hidePopover(this: HTMLElement) {
      this.toggleAttribute('data-popover-open', false);
    };
  }
  if (typeof Element.prototype.scrollIntoView !== 'function') {
    Element.prototype.scrollIntoView = function scrollIntoView() {};
  }
  beforeEach(() => {
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} }));
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      disconnect() {}
    });
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });
}

/** Answers every fetch with the JSON the route gives for the request's path. */
export function stubFetch(route: (path: string) => unknown): void {
  vi.stubGlobal('fetch', vi.fn(async (input: string) => new Response(JSON.stringify(route(new URL(input, 'http://dashboard').pathname)))));
}

/**
 * The axe-core violations inside the rendered document; contrast is left to tokens.test.ts because jsdom has no layout, and
 * landmarks to the page shell a component renders into.
 */
export async function axeViolations(root: Element = document.body): Promise<string[]> {
  const results = await axe.run(root, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } });
  return results.violations.map((violation) => `${violation.id}: ${violation.nodes.map((node) => node.target.join(' ')).join(', ')}`);
}

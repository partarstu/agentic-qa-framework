// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

export const COPY_BLOCKED = 'The browser blocked copying. Select the lines and copy them by hand.';

/**
 * Copies the text, resolving with whether it worked: the Clipboard API is missing outside a secure context (a dashboard served
 * over plain HTTP on another host) and the browser may refuse the write.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

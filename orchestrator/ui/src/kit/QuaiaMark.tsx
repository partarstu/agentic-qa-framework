// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import emblemUrl from '../assets/quaia-emblem.png';
import './QuaiaMark.css';

/** The QuAIA mark: the emblem of the official logo, a ring of circuit traces. */
export function QuaiaMark({ size = 28 }: { size?: number }) {
  return <img className="quaia-mark" src={emblemUrl} width={size} height={size} alt="" aria-hidden="true" />;
}

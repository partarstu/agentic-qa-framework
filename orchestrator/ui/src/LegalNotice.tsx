// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import './LegalNotice.css';

const SOURCE_URL = 'https://github.com/partarstu/agentic-qa-framework';
const LICENSE_URL = 'https://www.gnu.org/licenses/agpl-3.0.html';

/**
 * The appropriate legal notices of AGPL-3.0 §5(d) and the source offer of §13, static, as the screen of an unreachable
 * orchestrator cannot fetch them.
 */
export function LegalNotice() {
  return (
    <footer className="legal-notice">
      <p>
        QuAIA™ · Copyright © 2025-2026 Taras Paruta · Licensed under the{' '}
        <a href={LICENSE_URL} target="_blank" rel="noreferrer">GNU AGPL-3.0</a>, provided without warranty ·{' '}
        <a href={SOURCE_URL} target="_blank" rel="noreferrer">Source code</a> ·{' '}
        <a href="/licenses.md" target="_blank" rel="noreferrer">Third-party licences</a>
      </p>
    </footer>
  );
}

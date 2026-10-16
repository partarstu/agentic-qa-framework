// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { RotateCcw, TriangleAlert } from 'lucide-react';
import { Component, Fragment, type ReactNode } from 'react';

interface State {
  failed: boolean;
  attempt: number;
}

/** Keeps a view that fails to render to itself, so the rest of the dashboard and an open sheet keep working; a class, as React offers no hook for it. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false, attempt: 0 };

  static getDerivedStateFromError(): Partial<State> {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) {
      return <Fragment key={this.state.attempt}>{this.props.children}</Fragment>;
    }
    return (
      <div className="empty-state" role="alert">
        <TriangleAlert size={32} />
        <strong>This view failed</strong>
        <p>The rest of the dashboard keeps working. Show the view again, or reload the page if it keeps failing.</p>
        <button type="button" onClick={() => this.setState({ failed: false, attempt: this.state.attempt + 1 })}>
          <RotateCcw size={16} />
          Show it again
        </button>
      </div>
    );
  }
}

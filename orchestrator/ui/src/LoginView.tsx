// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { CircleAlert, Eye, EyeOff, LoaderCircle } from 'lucide-react';
import { useActionState, useId, useState } from 'react';
import { login, type LoginResult } from './data/authApi';
import { IconButton } from './kit/IconButton';
import { QuaiaMark } from './kit/QuaiaMark';
import { LegalNotice } from './LegalNotice';
import './LoginView.css';

export function loginError(result: Exclude<LoginResult, { kind: 'ok' }>): string {
  switch (result.kind) {
    case 'rejected':
      return 'Wrong username or password.';
    case 'rate-limited':
      return result.retryAfterSeconds === null
        ? 'Too many attempts. Wait a minute, then try again.'
        : `Too many attempts. Try again in ${result.retryAfterSeconds} ${result.retryAfterSeconds === 1 ? 'second' : 'seconds'}.`;
    case 'failed':
      return 'The orchestrator does not answer. Check that it is running, then try again.';
  }
}

interface Props {
  /** Shown when a rejected request ended the last session. */
  expired: boolean;
  onLoggedIn: (username: string) => void;
}

export function LoginView({ expired, onLoggedIn }: Props) {
  const [revealed, setRevealed] = useState(false);
  const usernameId = useId();
  const passwordId = useId();
  const errorId = useId();
  const [error, submit, pending] = useActionState(async (_previous: string | null, form: FormData) => {
    const result = await login(String(form.get('username') ?? ''), String(form.get('password') ?? ''));
    if (result.kind === 'ok') {
      onLoggedIn(result.username);
      return null;
    }
    return loginError(result);
  }, null);

  return (
    <div className="entry">
      <main className="login">
        {expired && !error && <p className="note login-note" role="status">Your session has ended. Log in again.</p>}
        <form className="login-form card" action={submit}>
          <div className="login-head">
            <QuaiaMark size={36} />
            <div>
              <h1>QuAIA™ Orchestrator</h1>
              <p className="muted">Watch the agents, their tasks and logs.</p>
            </div>
          </div>
          <label htmlFor={usernameId}>Username</label>
          <input id={usernameId} name="username" type="text" autoComplete="username" required autoFocus spellCheck={false} />
          <label htmlFor={passwordId}>Password</label>
          <div className="password-field">
            <input id={passwordId} name="password" type={revealed ? 'text' : 'password'} autoComplete="current-password" required
              aria-invalid={error ? true : undefined} aria-describedby={error ? errorId : undefined} />
            <IconButton icon={revealed ? EyeOff : Eye} label="Show password" small aria-pressed={revealed} onClick={() => setRevealed(!revealed)} />
          </div>
          {error && (
            <p id={errorId} className="alert" role="alert">
              <CircleAlert size={18} />
              {error}
            </p>
          )}
          <button type="submit" className="primary" disabled={pending} aria-busy={pending}>
            {pending && <LoaderCircle size={18} className="spin" />}
            {pending ? 'Logging in…' : 'Log in'}
          </button>
        </form>
      </main>
      <LegalNotice />
    </div>
  );
}

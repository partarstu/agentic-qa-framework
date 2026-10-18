// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/tokens.css';
import './styles/base.css';
import './styles/common.css';
import '@fontsource-variable/atkinson-hyperlegible-next';
import '@fontsource-variable/atkinson-hyperlegible-mono';
import { App } from './App';
import { initColorScheme } from './colorScheme';

initColorScheme();

const logRenderError = (error: unknown, info: { componentStack?: string }) =>
  console.error('A view of the dashboard failed to render', error, info.componentStack);

createRoot(document.getElementById('root')!, { onCaughtError: logRenderError, onUncaughtError: logRenderError }).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

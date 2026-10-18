// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { defineConfig } from 'vitest/config';
import react, { reactCompilerPreset } from '@vitejs/plugin-react';
import babel from '@rolldown/plugin-babel';
import type { Plugin } from 'vite';

const LAYER_ORDER_SHEET = '/layers.css';

/** Fails the build unless the page links the layer order before the bundle's sheets, whose chunks come in no fixed order. */
function layerOrderFirst(): Plugin {
  return {
    name: 'layer-order-first',
    apply: 'build',
    enforce: 'post',
    generateBundle(_options, bundle) {
      const page = bundle['index.html'];
      const html = page?.type === 'asset' ? String(page.source) : '';
      const first = /<link rel="stylesheet"[^>]*href="([^"]+)"/.exec(html)?.[1];
      if (first !== LAYER_ORDER_SHEET) {
        this.error(`index.html links ${first ?? 'no stylesheet'} first instead of ${LAYER_ORDER_SHEET}, so the layers would rank by chunk order`);
      }
    },
  };
}

export default defineConfig(({ command, mode, isPreview }) => {
  const orchestratorPort = process.env.ORCHESTRATOR_PORT;
  // Vitest loads this config as a dev server in test mode, and the tests need no orchestrator
  if (command === 'serve' && !isPreview && mode !== 'test' && !orchestratorPort) {
    throw new Error('ORCHESTRATOR_PORT environment variable is not defined');
  }
  return {
    plugins: [react(), babel({ presets: [reactCompilerPreset()] }), layerOrderFirst()],
    server: {
      proxy: orchestratorPort ? { '/api': { target: `http://localhost:${orchestratorPort}`, changeOrigin: true } } : undefined,
    },
    // Vitest empties CSS imports unless included; the style tests read stylesheets raw, while the components' imports stay empty
    test: { css: { include: /\.css\?raw$/ } },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
      license: { fileName: 'licenses.md' },
    },
  };
});

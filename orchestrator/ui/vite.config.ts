import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(({ command }) => {
  if (command === 'serve') {
    // Ensure ORCHESTRATOR_PORT is set for dev server proxy
    const orchestratorPort = process.env.ORCHESTRATOR_PORT;
    if (!orchestratorPort) {
      throw new Error("ORCHESTRATOR_PORT environment variable is not defined");
    }

    return {
      plugins: [react(), tailwindcss()],
      server: {
        proxy: {
          '/api': {
            target: `http://localhost:${orchestratorPort}`,
            changeOrigin: true,
          },
        },
      },
      build: {
        outDir: 'dist',
        emptyOutDir: true,
      },
    }
  }

  // Production build config (static files dont need the port)
  return {
    plugins: [react(), tailwindcss()],
    build: {
      outDir: 'dist',
      emptyOutDir: true,
    },
  }
})

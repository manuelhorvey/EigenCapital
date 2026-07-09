/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { visualizer } from 'rollup-plugin-visualizer'

export default defineConfig({
  plugins: [
    react(),
    visualizer({
      open: process.env.ANALYZE === 'true',
      gzipSize: true,
      brotliSize: true,
      filename: 'dist/stats.html',
    }),
  ],
  base: '/',
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test-setup.ts',
    exclude: ['e2e/**', 'node_modules/**'],
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('/react/') || id.includes('/react-dom/')) return 'react'
          if (id.includes('@tanstack/react-query')) return 'query'
          if (id.includes('/recharts/')) return 'recharts'
          if (id.includes('/lucide-react/')) return 'icons'
          if (id.includes('/zod/')) return 'validation'
          return undefined
        },
      },
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/state-bundle.json': 'http://localhost:5000',
      '/trades.json': 'http://localhost:5000',
      '/trade-outcomes.json': 'http://localhost:5000',
      '/equity_history.json': 'http://localhost:5000',
      '/wal/': 'http://localhost:5000',
      '/asset/': 'http://localhost:5000',
      '/health': 'http://localhost:5000',
      '/optimization.json': 'http://localhost:5000',
      '/healthcheck.json': 'http://localhost:5000',
      '/weekly-review.json': 'http://localhost:5000',
      '/weekly-review/acknowledge': 'http://localhost:5000',
      '/execution/': 'http://localhost:5000',
      '/attribution/': 'http://localhost:5000',
    },
  },
})

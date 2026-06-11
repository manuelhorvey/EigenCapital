import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('/react/') || id.includes('/react-dom/')) return 'react'
          if (id.includes('@tanstack/react-query')) return 'query'
          if (id.includes('/d3-')) return 'd3'
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
      '/state.json': 'http://localhost:5000',
      '/trades.json': 'http://localhost:5000',
      '/equity_history.json': 'http://localhost:5000',
      '/confidence.json': 'http://localhost:5000',
      '/volatility.json': 'http://localhost:5000',
      '/logs': 'http://localhost:5000',
      '/risk.json': 'http://localhost:5000',
      '/health.json': 'http://localhost:5000',
      '/shadow-actions': 'http://localhost:5000',
      '/governance.json': 'http://localhost:5000',
      '/liquidity.json': 'http://localhost:5000',
      '/narrative.json': 'http://localhost:5000',
      '/narrative/confirm': 'http://localhost:5000',
      '/psi.json': 'http://localhost:5000',
      '/risk-parity.json': 'http://localhost:5000',
      '/weekly-review.json': 'http://localhost:5000',
      '/weekly-review/acknowledge': 'http://localhost:5000',
    },
  },
})

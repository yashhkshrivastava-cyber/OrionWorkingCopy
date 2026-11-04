import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

/**
 * Libraries that rarely change get their own files, so a release that only touches Orion's pages leaves them in the browser's cache,
 * and the charts (the largest, used by the dashboards only) are fetched when a dashboard is opened, not with the app.
 * The icons are not a chunk of their own: each icon travels with the pages that use it, so opening the app downloads only the icons the shell draws.
 */
function vendorChunk(id: string): string | undefined {
  if (!id.includes('node_modules')) return undefined
  if (/node_modules\/(recharts|recharts-scale|victory-vendor|d3-[a-z-]+|internmap|decimal\.js-light|fast-equals|eventemitter3|tiny-invariant|lodash|react-smooth)\//.test(id)) return 'vendor-charts'
  if (/node_modules\/(react-router|react-router-dom|@remix-run|cookie|set-cookie-parser)\//.test(id)) return 'vendor-router'
  if (/node_modules\/(react|react-dom|scheduler)\//.test(id)) return 'vendor-react'
  return undefined
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { rollupOptions: { output: { manualChunks: vendorChunk } } },
  server: {
    host: true,
    port: 5173,
    // Tailscale MagicDNS names (*.ts.net) and the 100.x tailnet IP.
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})

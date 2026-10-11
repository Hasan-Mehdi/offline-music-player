import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// Dev server proxies the API + audio to the Flask backend (scripts/server.py on :5000).
// Production: `npm run build` -> web/dist, which server.py serves at / (same origin).
export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:5000',
      '/audio': 'http://127.0.0.1:5000',
    },
  },
})

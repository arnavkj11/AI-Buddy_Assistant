/* eslint-disable */
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  // Load base .env (no mode suffix) to get the real API Gateway URL for proxy target.
  // This is separate from the mode-specific .env.development override below.
  const baseEnv = loadEnv('', process.cwd(), '')
  const prodApiUrl = baseEnv.VITE_API_URL || ''

  let proxyConfig: Record<string, object> = {}
  if (prodApiUrl && prodApiUrl.startsWith('http')) {
    const url = new URL(prodApiUrl)
    proxyConfig = {
      '/api-proxy': {
        target: url.origin,
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/api-proxy/, url.pathname),
        secure: true,
      }
    }
  }

  return {
    plugins: [react()],
    server: {
      proxy: proxyConfig
    }
  }
})

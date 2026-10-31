import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/v1': {
        target: process.env.VITE_POOL_ENGINE_URL || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  resolve: {
    extensions: ['.ts', '.tsx', '.mjs', '.js', '.jsx', '.json']
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('firebase/firestore') || id.includes('@firebase/firestore')) {
            return 'vendor-firestore'
          }
          if (id.includes('firebase/auth') || id.includes('@firebase/auth')) {
            return 'vendor-auth'
          }
          if (id.includes('firebase/app') || id.includes('@firebase/app') || id.includes('firebase/messaging') || id.includes('firebase/analytics')) {
            return 'vendor-firebase-core'
          }
          if (id.includes('lucide-react')) {
            return 'vendor-lucide'
          }
        },
      },
    },
  },
})

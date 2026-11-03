import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/media': 'http://localhost:8000',
      '/api': 'http://localhost:8000',
      '/files': 'http://localhost:8000',
      '/thumbs': 'http://localhost:8000',
      '/compressed': 'http://localhost:8000',
    },
  },
})

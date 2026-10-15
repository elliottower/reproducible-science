import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Built into the Python package, which serves it. Relative paths, so the page works from any
// address the server is reached at.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: { outDir: '../src/repro_ui/static', emptyOutDir: true },
})

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  // Read VITE_* vars from the repo-root .env so the project has one env file.
  envDir: '..',
})

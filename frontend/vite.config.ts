import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Read the repository-root .env rather than frontend/.env, so the shared
  // secret is configured in exactly one place instead of two files that have to
  // agree. Only VITE_-prefixed variables are exposed to the bundle, so the SMTP
  // password and provider keys sitting in the same file stay server-side.
  envDir: '..',
})

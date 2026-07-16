/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string
  readonly VITE_API_TIMEOUT_MS?: string
  readonly VITE_HEALTH_POLL_MS?: string
  readonly VITE_BUILD_COMMIT?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

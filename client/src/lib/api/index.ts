// The single seam every component calls through — never `fetch` directly.
// `VITE_API_MODE=http` talks to the FastAPI backend (see ./http.ts); the
// default `mock` fakes it in the browser. Switching is a config change, not
// a rewrite of callers.

import type { ApiClient } from './client'
import { HttpApiClient } from './http'
import { MockApiClient } from './mock'

export { CLIP_AFTER_SECONDS, CLIP_BEFORE_SECONDS } from './mock'

const mode = import.meta.env.VITE_API_MODE ?? 'mock'

export const api: ApiClient = mode === 'http' ? new HttpApiClient() : new MockApiClient()

export { ApiError } from './client'
export type { ApiClient } from './client'
export * from './types'

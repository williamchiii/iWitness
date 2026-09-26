// The single seam every component calls through — never `fetch` directly.
// `VITE_API_MODE=http` is reserved for once the corresponding server
// endpoints exist (most of docs/api_contract.md's "Signed in" section and
// the incident endpoints don't yet — see server/api.py); switching to it is
// meant to be a one-line config change, not a rewrite of callers.

import type { ApiClient } from './client'
import { MockApiClient } from './mock'

export { CLIP_AFTER_SECONDS, CLIP_BEFORE_SECONDS } from './mock'

const mode = import.meta.env.VITE_API_MODE ?? 'mock'

function createApiClient(): ApiClient {
  if (mode === 'http') {
    throw new Error(
      'VITE_API_MODE=http is not implemented yet: the backend does not have ' +
        'auth or incident endpoints. Use VITE_API_MODE=mock (the default).',
    )
  }
  return new MockApiClient()
}

export const api: ApiClient = createApiClient()

export { ApiError } from './client'
export type { ApiClient } from './client'
export * from './types'

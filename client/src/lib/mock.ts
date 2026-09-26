// Stand-ins for the incident endpoints, so the UI can be built before the
// backend exists. Swap these for real calls later.

export interface Incident {
  id: string
  cameraId: string
  triggerAt: number
  // Unsaved footage is deleted after this time. Null once saved to an account.
  expiresAt: number | null
  saved: boolean
}

const CLAIM_WINDOW_MS = 15 * 60 * 1000

// How much footage a press keeps. Server settings PRE_TRIGGER_SECONDS and
// POST_TRIGGER_SECONDS in docs/api_contract.md; keep these in step with them.
export const CLIP_BEFORE_SECONDS = 60
export const CLIP_AFTER_SECONDS = 15

function delay(ms = 400) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export async function reportIncident(cameraId: string, signedIn: boolean): Promise<Incident> {
  const triggerAt = Date.now()
  await delay(250)
  return {
    id: crypto.randomUUID(),
    cameraId,
    triggerAt,
    expiresAt: signedIn ? null : triggerAt + CLAIM_WINDOW_MS,
    saved: signedIn,
  }
}

export async function saveIncident(incident: Incident): Promise<Incident> {
  await delay(250)
  return { ...incident, expiresAt: null, saved: true }
}

// Stand-ins for Supabase Google sign-in and the incident endpoints, so the UI
// can be built before the backend exists. Swap these for real calls later.

export interface User {
  email: string
  name: string
}

export interface Incident {
  id: string
  cameraId: string
  triggerAt: number
  // Unsaved footage is deleted after this time. Null once saved to an account.
  expiresAt: number | null
  saved: boolean
}

const CLAIM_WINDOW_MS = 15 * 60 * 1000

function delay(ms = 400) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export async function signInWithGoogle(): Promise<User> {
  await delay()
  return { email: 'student@example.com', name: 'Test Student' }
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

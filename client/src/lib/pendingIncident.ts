import type { Incident } from './mock'

// An incident pressed while logged out. Kept in sessionStorage so it survives the
// Google sign-in redirect (and a reload) in this tab; the footage itself is only
// deleted once incident.expiresAt passes without a login.
const KEY = 'iwitness.pendingIncident'

export function readPendingIncident(): Incident | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as Incident) : null
  } catch {
    return null
  }
}

export function storePendingIncident(incident: Incident) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(incident))
  } catch {
    // Storage blocked: the incident still works until the page is left.
  }
}

export function clearPendingIncident() {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    // Nothing stored if storage is blocked.
  }
}

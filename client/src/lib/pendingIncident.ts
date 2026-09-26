import type { Incident } from './api/types'

// An incident pressed while logged out, plus the trip token needed to claim
// it. Kept in sessionStorage so it survives the Google sign-in redirect (and
// a reload) in this tab; the footage itself is only deleted once
// incident.expires_at passes without a login.
const KEY = 'iwitness.pendingIncident'

export interface PendingIncident {
  incident: Incident
  tripToken: string
}

export function readPendingIncident(): PendingIncident | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as PendingIncident) : null
  } catch {
    return null
  }
}

export function storePendingIncident(pending: PendingIncident) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(pending))
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

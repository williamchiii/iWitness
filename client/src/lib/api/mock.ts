// In-memory stand-in for the backend, shaped exactly like docs/api_contract.md
// so switching to a real `http` implementation later is a config change, not
// a rewrite. Enforces the same rules the real API will: a trip token gates
// buffer/incident access, an incident can only be claimed once, and every
// signed-in endpoint requires `signedIn`. There is only ever one mock
// account, so "ownership" here just means "signed in" — see ApiClient's
// doc comment.

import { cameraPlaces } from '../cameras'
import type { ApiClient } from './client'
import { ApiError } from './client'
import type { BufferInfo, Camera, Incident, Playback, StartTripResponse, Trip, User } from './types'

export const CLIP_BEFORE_SECONDS = 60
export const CLIP_AFTER_SECONDS = 15
const CLAIM_WINDOW_SECONDS = 15 * 60
// After the post-trigger window closes, how long "assembling" takes before the clip is ready.
const ASSEMBLE_SECONDS = 3
// About the recorder's 1 Mbps, for a plausible file size.
const BYTES_PER_SECOND = 125_000

const MOCK_USER: User = {
  id: 'mock-user-1',
  email: 'student@example.com',
  display_name: 'Test Student',
  avatar_url: null,
}

// Stands in for the camera's own loop buffer until a real one exists.
const SAMPLE_STREAM_URL = 'https://demo.unified-streaming.com/k8s/live/stable/live.isml/.m3u8'

// A closed clip of just this window, cut from the sample stream's ~10 minute
// archive (Unified Streaming virtual subclip), so a saved clip really shows the
// moments around the press, clock and all. Clips older than that archive stop playing.
function clipUrl(startIso: string, endIso: string) {
  const seconds = (iso: string) => iso.replace(/\.\d{3}Z$/, 'Z')
  return `${SAMPLE_STREAM_URL}?vbegin=${seconds(startIso)}&vend=${seconds(endIso)}`
}

function delay(ms = 250) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function isoNow(): string {
  return new Date().toISOString()
}

function isoPlusSeconds(iso: string, seconds: number): string {
  return new Date(new Date(iso).getTime() + seconds * 1000).toISOString()
}

// Saved incidents (and the trip tokens that can claim them) are kept in
// localStorage, standing in for the backend's database: the Library then
// survives a reload, and a claim still works after the Google sign-in
// redirect. Trips stay in memory; a camera starts a new one when opened.
const STORAGE_KEY = 'iwitness.mockIncidents'

interface StoredIncidents {
  incidents: Incident[]
  tripTokens: [string, string][]
}

interface StoredTrip {
  trip: Trip
  tripToken: string
}

export class MockApiClient implements ApiClient {
  private trips = new Map<string, StoredTrip>()
  private incidents = new Map<string, Incident>()
  private incidentTripTokens = new Map<string, string>()

  constructor() {
    this.load()
  }

  async listCameras(): Promise<Camera[]> {
    await delay()
    return cameraPlaces.map((camera) => ({
      id: camera.id,
      name: camera.name,
      location: camera.direction,
      source_type: 'replay',
      recording: true,
    }))
  }

  async startTrip(cameraId: string): Promise<StartTripResponse> {
    await delay()
    if (!cameraPlaces.some((camera) => camera.id === cameraId)) {
      throw new ApiError(404, 'Camera not found')
    }

    const trip: Trip = {
      id: crypto.randomUUID(),
      camera_id: cameraId,
      started_at: isoNow(),
      ended_at: null,
      state: 'active',
    }
    const tripToken = crypto.randomUUID()
    this.trips.set(trip.id, { trip, tripToken })
    return { trip, trip_token: tripToken }
  }

  async endTrip(tripId: string, tripToken: string): Promise<Trip> {
    await delay()
    const stored = this.requireTrip(tripId, tripToken)
    stored.trip = { ...stored.trip, state: 'ended', ended_at: isoNow() }
    return stored.trip
  }

  async getBuffer(tripId: string, tripToken: string): Promise<BufferInfo> {
    await delay()
    const stored = this.requireTrip(tripId, tripToken)
    return {
      camera_id: stored.trip.camera_id,
      playlist_url: SAMPLE_STREAM_URL,
      earliest: null,
      latest: null,
    }
  }

  async reportIncident(tripId: string, tripToken: string, signedIn: boolean): Promise<Incident> {
    await delay()
    const stored = this.requireTrip(tripId, tripToken)
    const camera = cameraPlaces.find((c) => c.id === stored.trip.camera_id)
    const triggerAt = isoNow()

    const incident: Incident = {
      id: crypto.randomUUID(),
      trip_id: tripId,
      camera_id: stored.trip.camera_id,
      camera_name: camera?.name ?? stored.trip.camera_id,
      source_type: 'replay',
      trigger_at: triggerAt,
      requested_start: isoPlusSeconds(triggerAt, -CLIP_BEFORE_SECONDS),
      requested_end: isoPlusSeconds(triggerAt, CLIP_AFTER_SECONDS),
      actual_start: null,
      actual_end: null,
      source_start: null,
      source_end: null,
      duration_seconds: null,
      size_bytes: null,
      sha256: null,
      processing_state: 'recording',
      claim_state: signedIn ? 'claimed' : 'unclaimed',
      expires_at: signedIn ? null : isoPlusSeconds(triggerAt, CLAIM_WINDOW_SECONDS),
      video_version: 1,
      error: null,
    }

    this.incidents.set(incident.id, incident)
    this.incidentTripTokens.set(incident.id, tripToken)
    this.persist()
    return incident
  }

  async getMe(signedIn: boolean): Promise<User> {
    await delay()
    this.requireSignedIn(signedIn)
    return MOCK_USER
  }

  async claimIncident(incidentId: string, tripToken: string, signedIn: boolean): Promise<Incident> {
    await delay()
    this.requireSignedIn(signedIn)
    const incident = this.requireIncident(incidentId)

    if (incident.claim_state === 'claimed') {
      throw new ApiError(409, 'Incident already claimed')
    }
    if (incident.claim_state === 'expired' || (incident.expires_at && Date.now() >= Date.parse(incident.expires_at))) {
      const expired: Incident = { ...incident, claim_state: 'expired' }
      this.incidents.set(incidentId, expired)
      this.persist()
      throw new ApiError(410, 'Incident expired before it was claimed')
    }
    if (this.incidentTripTokens.get(incidentId) !== tripToken) {
      throw new ApiError(403, 'Invalid trip token')
    }

    const claimed: Incident = { ...incident, claim_state: 'claimed', expires_at: null }
    this.incidents.set(incidentId, claimed)
    this.persist()
    return this.advance(claimed)
  }

  async listIncidents(signedIn: boolean): Promise<Incident[]> {
    await delay()
    this.requireSignedIn(signedIn)
    return [...this.incidents.values()]
      .map((incident) => this.advance(incident))
      .filter((incident) => incident.claim_state === 'claimed')
      .sort((a, b) => Date.parse(b.trigger_at) - Date.parse(a.trigger_at))
  }

  async getIncident(incidentId: string, signedIn: boolean): Promise<Incident> {
    await delay()
    this.requireSignedIn(signedIn)
    return this.requireOwnedIncident(incidentId)
  }

  async getPlayback(incidentId: string, signedIn: boolean): Promise<Playback> {
    await delay()
    this.requireSignedIn(signedIn)
    const incident = this.requireOwnedIncident(incidentId)
    if (incident.processing_state !== 'ready') {
      throw new ApiError(409, 'Clip is not ready yet')
    }
    return {
      incident_id: incident.id,
      video_version: incident.video_version,
      playback_url: clipUrl(incident.actual_start!, incident.actual_end!),
      // The same window as MP4 fragments, which lib/download.ts stitches into
      // one .mp4 (the demo server won't serve a single MP4 file).
      download_url: `${clipUrl(incident.actual_start!, incident.actual_end!)}&hls_fmp4`,
      expires_at: isoPlusSeconds(isoNow(), 300),
    }
  }

  async deleteIncident(incidentId: string, signedIn: boolean): Promise<void> {
    await delay()
    this.requireSignedIn(signedIn)
    this.requireOwnedIncident(incidentId)
    this.incidents.delete(incidentId)
    this.incidentTripTokens.delete(incidentId)
    this.persist()
  }

  private requireSignedIn(signedIn: boolean): void {
    if (!signedIn) throw new ApiError(401, 'Sign-in required')
  }

  private requireTrip(tripId: string, tripToken: string): StoredTrip {
    const stored = this.trips.get(tripId)
    if (!stored) throw new ApiError(404, 'Trip not found')
    if (stored.tripToken !== tripToken) throw new ApiError(403, 'Invalid trip token')
    return stored
  }

  private requireIncident(incidentId: string): Incident {
    const incident = this.incidents.get(incidentId)
    if (!incident) throw new ApiError(404, 'Incident not found')
    return this.advance(incident)
  }

  // Processing moves recording -> assembling -> ready on a short timer, as the
  // contract's mock describes. Worked out from the clock on each read, so there
  // are no timers to clean up. The real backend reports the segment-aligned
  // actual window; here it simply equals the requested one.
  private advance(incident: Incident): Incident {
    if (incident.processing_state === 'ready' || incident.processing_state === 'failed') return incident
    const recordedUntil = Date.parse(incident.requested_end)
    const now = Date.now()
    let next: Incident
    if (now < recordedUntil) {
      next = { ...incident, processing_state: 'recording' }
    } else if (now < recordedUntil + ASSEMBLE_SECONDS * 1000) {
      next = { ...incident, processing_state: 'assembling' }
    } else {
      const duration = (recordedUntil - Date.parse(incident.requested_start)) / 1000
      next = {
        ...incident,
        processing_state: 'ready',
        actual_start: incident.requested_start,
        actual_end: incident.requested_end,
        duration_seconds: duration,
        size_bytes: Math.round(duration * BYTES_PER_SECOND),
      }
    }
    this.incidents.set(incident.id, next)
    this.persist()
    return next
  }

  private load(): void {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (!raw) return
      const stored = JSON.parse(raw) as StoredIncidents
      for (const incident of stored.incidents) this.incidents.set(incident.id, incident)
      for (const [id, token] of stored.tripTokens) this.incidentTripTokens.set(id, token)
    } catch {
      // Unreadable or blocked storage: start empty, like a fresh backend.
    }
  }

  private persist(): void {
    try {
      const stored: StoredIncidents = {
        incidents: [...this.incidents.values()],
        tripTokens: [...this.incidentTripTokens],
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(stored))
    } catch {
      // Storage blocked: incidents last until the page is reloaded.
    }
  }

  // Only a claimed incident is "owned" by the signed-in account in this
  // single-account mock; matches the contract's "404, or not yours" rule.
  private requireOwnedIncident(incidentId: string): Incident {
    const incident = this.requireIncident(incidentId)
    if (incident.claim_state !== 'claimed') throw new ApiError(404, 'Incident not found')
    return incident
  }
}

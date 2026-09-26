// In-memory stand-in for the backend, shaped exactly like docs/api_contract.md
// so switching to a real `http` implementation later is a config change, not
// a rewrite. Enforces the same rules the real API will: a trip token gates
// buffer/incident access, an incident can only be claimed once, and every
// signed-in endpoint requires `signedIn`. There is only ever one mock
// account, so "ownership" here just means "signed in" — see ApiClient's
// doc comment.

import { cameras as cameraCatalog } from '../cameras'
import type { ApiClient } from './client'
import { ApiError } from './client'
import type { BufferInfo, Camera, Incident, Playback, StartTripResponse, Trip, User } from './types'

export const CLIP_BEFORE_SECONDS = 60
export const CLIP_AFTER_SECONDS = 15
const CLAIM_WINDOW_SECONDS = 15 * 60

const MOCK_USER: User = {
  id: 'mock-user-1',
  email: 'student@example.com',
  display_name: 'Test Student',
  avatar_url: null,
}

// Stands in for the camera's own loop buffer until a real one exists.
const SAMPLE_STREAM_URL = 'https://demo.unified-streaming.com/k8s/live/stable/live.isml/.m3u8'

function delay(ms = 250) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function isoNow(): string {
  return new Date().toISOString()
}

function isoPlusSeconds(iso: string, seconds: number): string {
  return new Date(new Date(iso).getTime() + seconds * 1000).toISOString()
}

interface StoredTrip {
  trip: Trip
  tripToken: string
}

export class MockApiClient implements ApiClient {
  private trips = new Map<string, StoredTrip>()
  private incidents = new Map<string, Incident>()
  private incidentTripTokens = new Map<string, string>()

  async listCameras(): Promise<Camera[]> {
    await delay()
    return cameraCatalog.map((camera) => ({
      id: camera.id,
      name: camera.name,
      location: camera.direction,
      source_type: 'replay',
      recording: true,
    }))
  }

  async startTrip(cameraId: string): Promise<StartTripResponse> {
    await delay()
    if (!cameraCatalog.some((camera) => camera.id === cameraId)) {
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
    const camera = cameraCatalog.find((c) => c.id === stored.trip.camera_id)
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
      throw new ApiError(410, 'Incident expired before it was claimed')
    }
    if (this.incidentTripTokens.get(incidentId) !== tripToken) {
      throw new ApiError(403, 'Invalid trip token')
    }

    const claimed: Incident = {
      ...incident,
      claim_state: 'claimed',
      expires_at: null,
      processing_state: 'ready',
    }
    this.incidents.set(incidentId, claimed)
    return claimed
  }

  async listIncidents(signedIn: boolean): Promise<Incident[]> {
    await delay()
    this.requireSignedIn(signedIn)
    return [...this.incidents.values()]
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
      playback_url: SAMPLE_STREAM_URL,
      download_url: SAMPLE_STREAM_URL,
      expires_at: isoPlusSeconds(isoNow(), 300),
    }
  }

  async deleteIncident(incidentId: string, signedIn: boolean): Promise<void> {
    await delay()
    this.requireSignedIn(signedIn)
    this.requireOwnedIncident(incidentId)
    this.incidents.delete(incidentId)
    this.incidentTripTokens.delete(incidentId)
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
    return incident
  }

  // Only a claimed incident is "owned" by the signed-in account in this
  // single-account mock; matches the contract's "404, or not yours" rule.
  private requireOwnedIncident(incidentId: string): Incident {
    const incident = this.requireIncident(incidentId)
    if (incident.claim_state !== 'claimed') throw new ApiError(404, 'Incident not found')
    return incident
  }
}

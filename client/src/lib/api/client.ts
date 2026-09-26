import type {
  BufferInfo,
  Camera,
  Incident,
  Playback,
  StartTripResponse,
  Trip,
  User,
} from './types'

// Matches the `{ "detail": "..." }` shape every non-2xx response uses
// (docs/api_contract.md "Errors").
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
  }
}

// One function per endpoint in docs/api_contract.md. `signedIn` stands in for
// sending `Authorization: Bearer <token>` — the app doesn't expose a real
// access token yet (see lib/auth.ts), and there's only ever one signed-in
// account in this demo, so a boolean is enough for a client to decide what to
// call and for the mock to decide what to allow.
export interface ApiClient {
  listCameras(): Promise<Camera[]>
  // The contract allows an optional Authorization here to set the trip's
  // owner; not implemented — this mock has no concept of per-trip
  // ownership by account, only by trip token.
  startTrip(cameraId: string): Promise<StartTripResponse>
  endTrip(tripId: string, tripToken: string): Promise<Trip>
  getBuffer(tripId: string, tripToken: string): Promise<BufferInfo>
  reportIncident(tripId: string, tripToken: string, signedIn: boolean): Promise<Incident>
  getMe(signedIn: boolean): Promise<User>
  claimIncident(incidentId: string, tripToken: string, signedIn: boolean): Promise<Incident>
  listIncidents(signedIn: boolean): Promise<Incident[]>
  getIncident(incidentId: string, signedIn: boolean): Promise<Incident>
  getPlayback(incidentId: string, signedIn: boolean): Promise<Playback>
  deleteIncident(incidentId: string, signedIn: boolean): Promise<void>
}

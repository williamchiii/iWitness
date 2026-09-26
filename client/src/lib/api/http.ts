// The real backend, shaped by docs/api_contract.md exactly like the mock.
// Requests go to /api, which the Vite proxy strips before they reach FastAPI.
// While signed in, every request carries the Supabase access token as
// `Authorization: Bearer`; the server derives the user from it. The
// interface's `signedIn` flag is only for the mock, so these methods leave it out.

import { getAccessToken } from '../auth'
import type { ApiClient } from './client'
import { ApiError } from './client'
import type { BufferInfo, Camera, Incident, Playback, StartTripResponse, Trip, User } from './types'

interface RequestOptions {
  method?: 'GET' | 'POST' | 'DELETE'
  body?: unknown
  tripToken?: string
}

// FastAPI's `{ "detail": "..." }`, or a fallback when the body is something else
// (a proxy error page, or a validation error whose detail is a list).
async function errorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') return body.detail
  } catch {
    // Not JSON.
  }
  return `HTTP ${response.status}`
}

async function request<T>(path: string, { method = 'GET', body, tripToken }: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {}
  const accessToken = await getAccessToken()
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  if (tripToken) headers['X-Trip-Token'] = tripToken
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const response = await fetch(`/api${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response))
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

const id = encodeURIComponent

export class HttpApiClient implements ApiClient {
  listCameras(): Promise<Camera[]> {
    return request('/cameras')
  }

  startTrip(cameraId: string): Promise<StartTripResponse> {
    return request('/trips', { method: 'POST', body: { camera_id: cameraId } })
  }

  endTrip(tripId: string, tripToken: string): Promise<Trip> {
    return request(`/trips/${id(tripId)}/end`, { method: 'POST', tripToken })
  }

  getBuffer(tripId: string, tripToken: string): Promise<BufferInfo> {
    return request(`/trips/${id(tripId)}/buffer`, { tripToken })
  }

  reportIncident(tripId: string, tripToken: string): Promise<Incident> {
    return request(`/trips/${id(tripId)}/incidents`, { method: 'POST', tripToken })
  }

  getMe(): Promise<User> {
    return request('/me')
  }

  claimIncident(incidentId: string, tripToken: string): Promise<Incident> {
    return request(`/incidents/${id(incidentId)}/claim`, { method: 'POST', tripToken })
  }

  listIncidents(): Promise<Incident[]> {
    return request('/incidents')
  }

  getIncident(incidentId: string): Promise<Incident> {
    return request(`/incidents/${id(incidentId)}`)
  }

  getPlayback(incidentId: string): Promise<Playback> {
    return request(`/incidents/${id(incidentId)}/playback`)
  }

  deleteIncident(incidentId: string): Promise<void> {
    return request(`/incidents/${id(incidentId)}`, { method: 'DELETE' })
  }
}

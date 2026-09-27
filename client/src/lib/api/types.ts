// Wire types, matching docs/api_contract.md exactly (field names included) so
// no mapping layer is needed once a real `http` implementation exists.

export type IsoTime = string

// 'replay' = a saved recording fed through the same pipeline. UI must label it.
export type SourceType = 'live' | 'replay'

export interface Camera {
  id: string
  name: string
  location: string
  source_type: SourceType
  recording: boolean
}

export type TripState = 'active' | 'ended'

export interface Trip {
  id: string
  camera_id: string
  started_at: IsoTime
  ended_at: IsoTime | null
  state: TripState
}

export interface StartTripResponse {
  trip: Trip
  trip_token: string
}

export interface BufferInfo {
  camera_id: string
  playlist_url: string
  earliest: IsoTime | null
  latest: IsoTime | null
}

// recording   post-trigger window still being recorded
// assembling  concatenating segments into clip.mp4
// uploading   copying the clip to private storage (after claim)
// ready       playable and downloadable
// failed      see `error`
export type ProcessingState = 'recording' | 'assembling' | 'uploading' | 'ready' | 'failed'

// unclaimed   pressed while signed out; waiting for sign-in until expires_at
// claimed     attached to the signed-in user
// expired     never claimed in time; video deleted
export type ClaimState = 'unclaimed' | 'claimed' | 'expired'

export interface Incident {
  id: string
  trip_id: string
  camera_id: string
  camera_name: string
  source_type: SourceType
  trigger_at: IsoTime
  requested_start: IsoTime
  requested_end: IsoTime
  actual_start: IsoTime | null
  actual_end: IsoTime | null
  source_start: IsoTime | null
  source_end: IsoTime | null
  duration_seconds: number | null
  size_bytes: number | null
  sha256: string | null
  processing_state: ProcessingState
  claim_state: ClaimState
  expires_at: IsoTime | null
  video_version: number
  error: string | null
  // JPEG still from the clip at the press, owner only; null until ready.
  thumbnail_url: string | null
  // When the server deletes this saved clip (30 days after the press); null unless claimed.
  deletes_at: IsoTime | null
}

export interface Playback {
  incident_id: string
  video_version: number
  playback_url: string
  download_url: string
  expires_at: IsoTime
}

export interface User {
  id: string
  email: string
  display_name: string | null
  avatar_url: string | null
}

import { useCallback, useEffect, useRef, useState } from 'react'
import type { Camera } from '../lib/cameras'
import { api } from '../lib/api'
import type { Incident, StartTripResponse } from '../lib/api/types'
import { readPendingIncident } from '../lib/pendingIncident'
import IncidentPanel from './IncidentPanel'
import Player from './Player'

interface Props {
  camera: Camera
  number: number
  signedIn: boolean
  onSignIn: () => Promise<void>
  onClose: () => void
  onSaved: (incident: Incident) => void
}

// A link that stops working sooner than this after it was issued isn't just expired.
const BUFFER_RETRY_MS = 30_000

export default function CameraModal({ camera, number, signedIn, onSignIn, onClose, onSaved }: Props) {
  // One trip per time this camera is opened; used to gate the buffer and
  // scope the incident button. Started immediately so a press doesn't have
  // to wait on it separately - see IncidentPanel.press().
  const [tripPromise] = useState<Promise<StartTripResponse>>(() => api.startTrip(camera.id))

  // The camera's loop buffer, as a signed playlist link. Links expire, so the
  // player asks for a new one; one that fails right away means something else is wrong.
  const [bufferUrl, setBufferUrl] = useState<string | null>(null)
  const [bufferFailed, setBufferFailed] = useState(false)
  const [bufferAttempt, setBufferAttempt] = useState(0)
  const bufferLoadedAt = useRef(0)

  useEffect(() => {
    let current = true
    tripPromise
      .then(({ trip, trip_token }) => api.getBuffer(trip.id, trip_token))
      .then((buffer) => {
        if (!current) return
        bufferLoadedAt.current = Date.now()
        setBufferUrl(buffer.playlist_url)
      })
      .catch(() => {
        if (current) setBufferFailed(true)
      })
    return () => {
      current = false
    }
  }, [tripPromise, bufferAttempt])

  const refreshBuffer = useCallback(() => {
    if (Date.now() - bufferLoadedAt.current < BUFFER_RETRY_MS) setBufferFailed(true)
    else setBufferAttempt((n) => n + 1)
  }, [])

  // Resume an incident pressed on this camera before the Google redirect or a reload.
  const [incident, setIncident] = useState<Incident | null>(() => {
    const pending = readPendingIncident()
    return pending?.incident.camera_id === camera.id ? pending.incident : null
  })
  // The trip token that authorizes claiming `incident` - the token from
  // *when it was pressed*, not necessarily this mount's fresh trip (the
  // Google redirect remounts everything, starting a new trip).
  const [tripToken, setTripToken] = useState<string | null>(() => {
    const pending = readPendingIncident()
    return pending?.incident.camera_id === camera.id ? pending.tripToken : null
  })
  const [busy, setBusy] = useState(false)
  // Block closing while a press is in flight, too: otherwise the panel
  // can unmount before it knows whether the incident needs to be kept.
  const unsaved = busy || (incident !== null && incident.claim_state !== 'claimed')

  const requestClose = useCallback(() => {
    if (unsaved && !window.confirm('Leave without saving? Footage you have not saved will be deleted.')) return
    onClose()
  }, [unsaved, onClose])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== 'Escape') return
      requestClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [requestClose])

  return (
    <div
      className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/20 p-4 backdrop-blur-md"
      onClick={requestClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="camera-title"
        className="max-h-full w-full max-w-3xl overflow-y-auto rounded-xl border border-line bg-white pb-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 px-6 pb-4 pt-5">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-muted">
              Cam {number}, {camera.direction}
            </p>
            <h2 id="camera-title" className="mt-1 text-2xl font-medium tracking-tight">
              {camera.name}
            </h2>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={requestClose}
            className="grid size-9 shrink-0 place-items-center rounded-md border border-line text-muted transition-colors hover:text-ink"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
        {bufferUrl && !bufferFailed ? (
          <Player
            src={bufferUrl}
            labels={camera.source_type === 'replay' ? ['Replayed'] : []}
            onExpired={refreshBuffer}
          />
        ) : (
          <div className="grid aspect-video place-items-center bg-black text-sm text-white/80">
            {bufferFailed && 'Video unavailable. Close and reopen the camera to try again.'}
          </div>
        )}
        <IncidentPanel
          tripPromise={tripPromise}
          signedIn={signedIn}
          onSignIn={onSignIn}
          onSaved={onSaved}
          incident={incident}
          onIncident={setIncident}
          tripToken={tripToken}
          onTripTokenChange={setTripToken}
          onBusyChange={setBusy}
        />
      </div>
    </div>
  )
}

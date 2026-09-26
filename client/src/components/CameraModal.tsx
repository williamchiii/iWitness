import { useCallback, useEffect, useState } from 'react'
import { SAMPLE_STREAM_URL } from '../lib/cameras'
import type { Camera } from '../lib/cameras'
import type { Incident } from '../lib/mock'
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

export default function CameraModal({ camera, number, signedIn, onSignIn, onClose, onSaved }: Props) {
  // Resume an incident pressed on this camera before the Google redirect or a reload.
  const [incident, setIncident] = useState<Incident | null>(() => {
    const pending = readPendingIncident()
    return pending?.cameraId === camera.id ? pending : null
  })
  const [busy, setBusy] = useState(false)
  // Block closing while a press is in flight, too: otherwise the panel
  // can unmount before it knows whether the incident needs to be kept.
  const unsaved = busy || (incident !== null && !incident.saved)

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
        <Player src={SAMPLE_STREAM_URL} labels={['Sample stream']} />
        <IncidentPanel
          cameraId={camera.id}
          signedIn={signedIn}
          onSignIn={onSignIn}
          onSaved={onSaved}
          incident={incident}
          onIncident={setIncident}
          onBusyChange={setBusy}
        />
      </div>
    </div>
  )
}

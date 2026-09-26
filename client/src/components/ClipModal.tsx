import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../lib/api'
import type { Incident, Playback } from '../lib/api/types'
import { cameraNumber, cameras } from '../lib/cameras'
import { formatClock, formatClockRange, formatDay, formatDuration } from '../lib/format'
import ClipPlayer from './ClipPlayer'

interface Props {
  incident: Incident
  onClose: () => void
}

function sourceLabel(incident: Incident) {
  return incident.source_type === 'replay' ? 'Replayed recording' : 'Live camera'
}

// One saved clip: player plus the details the brief asks for. Playback is only
// requested here, when a clip is opened, never for the whole list. Rendered on
// document.body: the Library's frosted panel (backdrop-filter) would otherwise
// become the containing block for this fixed overlay and trap it inside the panel.
export default function ClipModal({ incident, onClose }: Props) {
  const [playback, setPlayback] = useState<Playback | null>(null)
  const [error, setError] = useState<string | null>(null)
  const camera = cameras.find((c) => c.id === incident.camera_id)

  useEffect(() => {
    let current = true
    api
      .getPlayback(incident.id, true)
      .then((result) => {
        if (current) setPlayback(result)
      })
      .catch(() => {
        if (current) setError("This clip can't be played right now.")
      })
    return () => {
      current = false
    }
  }, [incident.id])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const start = Date.parse(incident.actual_start!)
  const end = Date.parse(incident.actual_end!)
  const trigger = Date.parse(incident.trigger_at)

  return createPortal(
    <div
      className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/20 p-4 backdrop-blur-md"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="clip-title"
        className="max-h-full w-full max-w-3xl overflow-y-auto rounded-xl border border-line bg-white pb-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 px-6 pb-4 pt-5">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-muted">
              {camera ? `Cam ${cameraNumber(camera.id)}, ${camera.direction}` : 'Saved clip'}
            </p>
            <h2 id="clip-title" className="mt-1 text-2xl font-medium tracking-tight">
              {incident.camera_name}
            </h2>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="grid size-9 shrink-0 place-items-center rounded-md border border-line text-muted transition-colors hover:text-ink"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        {playback ? (
          <ClipPlayer
            src={playback.playback_url}
            startMs={start}
            triggerMs={trigger}
            labels={[incident.source_type === 'replay' ? 'Replayed' : 'Live camera']}
          />
        ) : (
          <div className="grid aspect-video place-items-center bg-black text-sm text-white/70">{error ?? 'Loading clip...'}</div>
        )}

        <dl className="mt-5 grid grid-cols-1 gap-x-6 gap-y-3 px-6 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-muted">Recorded</dt>
            <dd className="mt-0.5 tabular-nums">
              {formatDay(start)}, {formatClockRange(start, end)}
            </dd>
          </div>
          <div>
            <dt className="text-muted">You pressed save</dt>
            <dd className="mt-0.5 tabular-nums">{formatClock(trigger)}</dd>
          </div>
          <div>
            <dt className="text-muted">Length</dt>
            <dd className="mt-0.5 tabular-nums">{formatDuration(incident.duration_seconds ?? (end - start) / 1000)}</dd>
          </div>
          <div>
            <dt className="text-muted">Source</dt>
            <dd className="mt-0.5">{sourceLabel(incident)}</dd>
          </div>
        </dl>

        <p className="mt-5 px-6 text-xs text-muted">
          This camera may not show your vehicle. Footage gives context, not proof of fault.
        </p>
      </div>
    </div>,
    document.body,
  )
}

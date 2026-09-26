import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../lib/api'
import type { Incident, Playback } from '../lib/api/types'
import { cameraNumber, cameras } from '../lib/cameras'
import { downloadFile } from '../lib/download'
import { formatClock, formatClockRange, formatDay, formatDuration, formatFileStamp } from '../lib/format'
import ClipPlayer from './ClipPlayer'

interface Props {
  incident: Incident
  onClose: () => void
}

// Signed links are short-lived: refresh one this close to expiring before using it.
const LINK_REFRESH_MARGIN_MS = 30_000

// iwitness_i-95-at-sw-8th-st_2026-09-26_143304.mp4
function downloadName(incident: Incident) {
  const camera = incident.camera_name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
  return `iwitness_${camera}_${formatFileStamp(Date.parse(incident.trigger_at))}.mp4`
}

function sourceLabel(incident: Incident) {
  return incident.source_type === 'replay' ? 'Replayed recording' : 'Live camera'
}

// One saved clip: player plus the details the brief asks for. Playback is only
// requested here, when a clip is opened, never for the whole list. Rendered on
// document.body: the Library's frosted panel (backdrop-filter) would otherwise
// become the containing block for this fixed overlay and trap it inside the panel.
export default function ClipModal({ incident, onClose }: Props) {
  // Newest playback links, used by Download. The player keeps the first URL it
  // got, so refreshing an expired link never restarts the video being watched.
  const [playback, setPlayback] = useState<Playback | null>(null)
  const [playerSrc, setPlayerSrc] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const camera = cameras.find((c) => c.id === incident.camera_id)

  useEffect(() => {
    let current = true
    api
      .getPlayback(incident.id, true)
      .then((result) => {
        if (!current) return
        setPlayback(result)
        setPlayerSrc(result.playback_url)
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

  // Saves the file directly, no new tab. An expired (or nearly expired) link is
  // swapped for a fresh one first.
  async function download() {
    if (!playback) return
    setDownloading(true)
    setDownloadError(null)
    try {
      let link = playback
      if (Date.now() >= Date.parse(link.expires_at) - LINK_REFRESH_MARGIN_MS) {
        link = await api.getPlayback(incident.id, true)
        setPlayback(link)
      }
      await downloadFile(link.download_url, downloadName(incident))
    } catch {
      setDownloadError('Could not download the clip. Try again.')
    } finally {
      setDownloading(false)
    }
  }

  const start = Date.parse(incident.actual_start!)
  const end = Date.parse(incident.actual_end!)
  const trigger = Date.parse(incident.trigger_at)

  return createPortal(
    <div
      className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/10 p-4 backdrop-blur-[2px]"
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
          <div className="flex shrink-0 items-center gap-2">
            {playback && (
              <button
                type="button"
                onClick={download}
                disabled={downloading}
                className="flex h-9 items-center gap-2 rounded-md border border-line px-3 text-sm font-medium transition-colors hover:bg-surface disabled:opacity-60"
              >
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M12 4v11m0 0-4.5-4.5M12 15l4.5-4.5M5 20h14" />
                </svg>
                {downloading ? 'Downloading...' : 'Download'}
              </button>
            )}
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
        </div>
        {downloadError && <p className="-mt-2 px-6 pb-3 text-right text-sm text-rec">{downloadError}</p>}

        {playerSrc ? (
          <ClipPlayer
            src={playerSrc}
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

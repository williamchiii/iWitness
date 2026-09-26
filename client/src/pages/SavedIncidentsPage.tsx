import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import ClipModal from '../components/ClipModal'
import Header from '../components/Header'
import MapBackdrop from '../components/MapBackdrop'
import SignInDialog from '../components/SignInDialog'
import Thumbnail from '../components/Thumbnail'
import Toast from '../components/Toast'
import type { ToastMessage } from '../components/Toast'
import { api } from '../lib/api'
import type { Incident } from '../lib/api/types'
import { signInWithGoogle, signOut } from '../lib/auth'
import { cameraNumber, cameraPlaces } from '../lib/cameras'
import { formatClock, formatClockRange, formatDay, formatDuration } from '../lib/format'
import { OUTLINE_PILL } from '../lib/styles'
import { useUser } from '../lib/useUser'

// docs/api_contract.md: poll GET /incidents/{id} every 2 to 3 s until ready or failed.
const POLL_MS = 2500

const isDone = (incident: Incident) => incident.processing_state === 'ready' || incident.processing_state === 'failed'

// What the clip covers. Only the actual window is shown, never the requested
// one; until the clip is assembled there is no actual window yet.
function recordedLine(incident: Incident) {
  if (incident.actual_start && incident.actual_end) {
    const start = Date.parse(incident.actual_start)
    const end = Date.parse(incident.actual_end)
    return `${formatDay(start)}, ${formatClockRange(start, end)}`
  }
  if (incident.processing_state === 'recording') return `Still recording until ${formatClock(Date.parse(incident.requested_end))}`
  if (incident.processing_state === 'failed') return incident.error ?? 'This clip could not be saved.'
  return 'Preparing the clip...'
}

const STATUS: Record<Incident['processing_state'], string> = {
  recording: 'Recording',
  assembling: 'Processing',
  uploading: 'Processing',
  ready: 'Ready',
  failed: 'Failed',
}

function Tag({ children }: { children: string }) {
  return <span className="rounded-md bg-surface px-2 py-1 text-xs font-medium text-muted">{children}</span>
}

function IncidentCard({ incident, onOpen }: { incident: Incident; onOpen: () => void }) {
  const camera = cameraPlaces.find((c) => c.id === incident.camera_id)
  const ready = incident.processing_state === 'ready'
  return (
    <button
      type="button"
      onClick={onOpen}
      disabled={!ready}
      className="glass-card flex w-full flex-col gap-4 rounded-xl border border-white/70 p-3 text-left transition-colors enabled:hover:border-white sm:flex-row sm:gap-5"
    >
      {/* A still from the clip at the press, like the camera list's snapshots. */}
      <Thumbnail
        src={ready ? (incident.thumbnail_url ?? null) : null}
        label="Saved clip"
        className="w-full self-start sm:w-48"
      >
        {ready ? (
          <span className="grid size-10 place-items-center rounded-full bg-white/90 text-ink shadow-sm">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">
              <path d="M7 4.5v15a1 1 0 0 0 1.5.86l12.5-7.5a1 1 0 0 0 0-1.72L8.5 3.64A1 1 0 0 0 7 4.5Z" />
            </svg>
          </span>
        ) : (
          <span className="text-xs text-muted">{STATUS[incident.processing_state]}...</span>
        )}
      </Thumbnail>
      <div className="flex min-w-0 flex-1 flex-col px-1 py-1 sm:px-0">
        {camera && (
          <p className="text-xs font-medium uppercase tracking-wider text-muted">
            Cam {cameraNumber(camera.id)}, {camera.direction}
          </p>
        )}
        <p className="mt-1 text-lg font-medium tracking-tight">{incident.camera_name}</p>
        <p className="text-sm tabular-nums text-muted">{recordedLine(incident)}</p>
        <p className="text-sm tabular-nums text-muted">Pressed at {formatClock(Date.parse(incident.trigger_at))}</p>
        <div className="mt-auto flex flex-wrap gap-2 pt-3">
          <Tag>{STATUS[incident.processing_state]}</Tag>
          <Tag>{incident.source_type === 'replay' ? 'Replayed recording' : 'Live camera'}</Tag>
          {incident.duration_seconds !== null && <Tag>{formatDuration(incident.duration_seconds)}</Tag>}
        </div>
      </div>
    </button>
  )
}

function SavedList({ onDeleted }: { onDeleted: (incident: Incident) => void }) {
  const [incidents, setIncidents] = useState<Incident[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [openId, setOpenId] = useState<string | null>(null)
  const closeClip = useCallback(() => setOpenId(null), [])
  const removeClip = useCallback(
    (deleted: Incident) => {
      setOpenId(null)
      setIncidents((list) => list && list.filter((i) => i.id !== deleted.id))
      onDeleted(deleted)
    },
    [onDeleted],
  )

  useEffect(() => {
    let current = true
    api
      .listIncidents(true)
      .then((list) => {
        if (!current) return
        setIncidents(list)
        setError(null)
      })
      .catch(() => {
        if (current) setError('Could not load your recordings.')
      })
    return () => {
      current = false
    }
  }, [attempt])

  // Refresh each clip still being recorded or assembled until it is ready.
  const pendingIds = (incidents ?? []).filter((i) => !isDone(i)).map((i) => i.id).join(',')
  useEffect(() => {
    if (!pendingIds) return
    const timer = setInterval(async () => {
      const updates = await Promise.all(pendingIds.split(',').map((id) => api.getIncident(id, true).catch(() => null)))
      setIncidents((list) => list && list.map((i) => updates.find((u) => u?.id === i.id) ?? i))
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [pendingIds])

  if (error) {
    return (
      <div className="glass-card mt-8 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-white/70 p-6">
        <p className="text-sm text-rec">{error}</p>
        <button type="button" onClick={() => setAttempt((n) => n + 1)} className={OUTLINE_PILL}>
          Try again
        </button>
      </div>
    )
  }

  if (!incidents) return <p className="mt-8 text-sm text-muted">Loading...</p>

  if (incidents.length === 0) {
    return (
      <div className="glass-card mt-8 rounded-xl border border-white/70 p-6">
        <p className="font-medium">No recordings yet.</p>
        <p className="mt-1 text-sm text-muted">Open a camera and press Save recording to keep the footage here.</p>
        <Link to="/" className={`mt-4 inline-block ${OUTLINE_PILL}`}>
          Browse cameras
        </Link>
      </div>
    )
  }

  const open = incidents.find((i) => i.id === openId && i.processing_state === 'ready')
  return (
    <>
      <ul className="mt-8 space-y-3">
        {incidents.map((incident) => (
          <li key={incident.id}>
            <IncidentCard incident={incident} onOpen={() => setOpenId(incident.id)} />
          </li>
        ))}
      </ul>
      {open && <ClipModal key={open.id} incident={open} onClose={closeClip} onDeleted={removeClip} />}
    </>
  )
}

// The signed-in user's saved clips (demo steps 4 and 5). Listing, playback and
// ownership are the API's job; this page only fetches and shows them.
export default function SavedIncidentsPage() {
  const { user, ready } = useUser()
  const [showSignIn, setShowSignIn] = useState(false)
  const [toast, setToast] = useState<ToastMessage | null>(null)
  const dismissToast = useCallback(() => setToast(null), [])
  const showDeleted = useCallback(
    (incident: Incident) =>
      setToast({
        id: Date.now(),
        tone: 'success',
        title: 'Clip deleted',
        body: `${incident.camera_name}, saved at ${formatClock(Date.parse(incident.trigger_at))}.`,
      }),
    [],
  )

  function logOut() {
    signOut().catch(() => setToast({ id: Date.now(), title: 'Could not log out.', body: 'Check your connection and try again.' }))
  }

  return (
    <div className="relative h-full">
      <Header user={user} link={{ to: '/', label: 'Cameras' }} onLogIn={() => setShowSignIn(true)} onLogOut={logOut} />
      <MapBackdrop />
      <main className="relative z-10 h-full overflow-y-auto px-4 pb-12 pt-28 md:pt-32">
        {/* Same frosted panel as the camera list, floating over the map. */}
        <div className="glass-pane mx-auto max-w-3xl rounded-2xl border border-white/60 p-6 md:p-8">
          <h1 className="text-3xl font-medium tracking-tight">Library</h1>
          <p className="mt-1 text-muted">Recordings you saved. Only you can see them.</p>

          {!ready && <p className="mt-8 text-sm text-muted">Loading...</p>}

          {ready && !user && (
            <div className="glass-card mt-8 rounded-xl border border-white/70 p-6">
              <p className="font-medium">Log in to see your recordings.</p>
              <p className="mt-1 text-sm text-muted">Saved clips are private to your account.</p>
              <button
                type="button"
                onClick={() => setShowSignIn(true)}
                className="mt-4 rounded-full bg-ink px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-black"
              >
                Log in
              </button>
            </div>
          )}

          {/* Keyed by account, so switching users never shows the previous one's list. */}
          {ready && user && <SavedList key={user.email} onDeleted={showDeleted} />}
        </div>
      </main>
      {toast && <Toast key={toast.id} toast={toast} onDismiss={dismissToast} />}
      {showSignIn && !user && <SignInDialog onSignIn={signInWithGoogle} onClose={() => setShowSignIn(false)} />}
    </div>
  )
}

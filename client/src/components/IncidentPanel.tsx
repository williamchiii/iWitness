import { useEffect, useRef, useState } from 'react'
import { formatClock, formatDuration } from '../lib/format'
import { reportIncident, saveIncident } from '../lib/mock'
import type { Incident } from '../lib/mock'
import { clearPendingIncident, storePendingIncident } from '../lib/pendingIncident'
import { useNow } from '../lib/useNow'
import SignInDialog from './SignInDialog'

interface Props {
  cameraId: string
  signedIn: boolean
  onSignIn: () => Promise<void>
  onIncident: (incident: Incident | null) => void
  incident: Incident | null
}

function Pending({ incident, signedIn, onLogIn }: { incident: Incident; signedIn: boolean; onLogIn: () => void }) {
  const secondsLeft = Math.max(0, (incident.expiresAt! - useNow()) / 1000)

  if (secondsLeft === 0) {
    return (
      <div className="mt-4 rounded-lg border border-line bg-surface p-4 text-sm">
        <p className="font-medium">Time ran out.</p>
        <p className="mt-1 text-muted">This footage was not saved and has been deleted.</p>
      </div>
    )
  }

  if (signedIn) {
    return (
      <div className="mt-4 rounded-lg border border-line bg-surface p-4 text-sm">
        <p>Saving to your account...</p>
      </div>
    )
  }

  return (
    <div className="mt-4 flex flex-wrap items-center justify-between gap-4 rounded-lg border border-line bg-surface p-4 text-sm">
      <div>
        <p>
          Pressed at <span className="tabular-nums">{formatClock(incident.triggerAt)}</span>. Footage from before
          your press is being kept.
        </p>
        <p className="mt-1 text-muted">
          Log in within <span className="font-medium tabular-nums text-ink">{formatDuration(secondsLeft)}</span> to
          save it, or it will be deleted.
        </p>
      </div>
      <button
        type="button"
        onClick={onLogIn}
        className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-white hover:bg-black"
      >
        Log in to save
      </button>
    </div>
  )
}

export default function IncidentPanel({ cameraId, signedIn, onSignIn, onIncident, incident }: Props) {
  const [busy, setBusy] = useState(false)
  const [showLogIn, setShowLogIn] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveAttempt, setSaveAttempt] = useState(0)
  const saving = useRef(false)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  async function press() {
    setBusy(true)
    const reported = await reportIncident(cameraId, signedIn)
    // The camera was closed while this was in flight: don't bring the incident back.
    if (!mounted.current) return
    if (!reported.saved) storePendingIncident(reported)
    onIncident(reported)
    setBusy(false)
    if (!reported.saved) setShowLogIn(true)
  }

  // Once the user is logged in, whether here or back from the Google redirect,
  // attach the pending incident to their account.
  useEffect(() => {
    if (!signedIn || !incident || incident.saved || saving.current) return
    if (incident.expiresAt !== null && Date.now() >= incident.expiresAt) return
    saving.current = true
    saveIncident(incident)
      .then((saved) => {
        clearPendingIncident()
        onIncident(saved)
      })
      .catch(() => setSaveError('Could not save this incident.'))
      .finally(() => {
        saving.current = false
      })
  }, [signedIn, incident, onIncident, saveAttempt])

  return (
    <div className="mt-6 border-t border-line px-6 pt-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="max-w-md">
          <p className="font-medium tracking-tight">In an incident?</p>
          <p className="mt-1 text-sm text-muted">
            Press the button and we keep this camera's footage from before the press, then record a little longer.
            You only log in to save it.
          </p>
        </div>
        <button
          type="button"
          onClick={press}
          disabled={busy || incident !== null}
          className="rounded-md bg-rec px-5 py-3 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {busy ? 'Keeping footage...' : 'I was in an incident'}
        </button>
      </div>

      {incident && !incident.saved && !saveError && (
        <Pending incident={incident} signedIn={signedIn} onLogIn={() => setShowLogIn(true)} />
      )}
      {saveError && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-4 rounded-lg border border-line bg-surface p-4 text-sm">
          <p className="text-rec">{saveError} Your footage is still being kept.</p>
          <button
            type="button"
            onClick={() => {
              setSaveError(null)
              setSaveAttempt((n) => n + 1)
            }}
            className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-white hover:bg-black"
          >
            Try again
          </button>
        </div>
      )}

      {incident?.saved && (
        <div className="mt-4 rounded-lg border border-line bg-surface p-4 text-sm">
          <p className="font-medium">Saved to your account.</p>
          <p className="mt-1 text-muted">
            Pressed at <span className="tabular-nums">{formatClock(incident.triggerAt)}</span>. It will appear in your
            Library when the clip is ready.
          </p>
        </div>
      )}

      <p className="mt-5 text-xs text-muted">
        This camera may not show your vehicle. Footage gives context, not proof of fault.
      </p>

      {showLogIn && !signedIn && incident && !incident.saved && (
        <SignInDialog
          deadline={incident.expiresAt!}
          onSignIn={onSignIn}
          onClose={() => setShowLogIn(false)}
        />
      )}
    </div>
  )
}

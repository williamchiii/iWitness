import { useEffect, useRef, useState } from 'react'
import { api, CLIP_AFTER_SECONDS, CLIP_BEFORE_SECONDS } from '../lib/api'
import type { Incident, StartTripResponse } from '../lib/api/types'
import { formatClock, formatDuration, formatSpan } from '../lib/format'
import { clearPendingIncident, storePendingIncident } from '../lib/pendingIncident'
import { useNow } from '../lib/useNow'
import SignInDialog from './SignInDialog'

interface Props {
  tripPromise: Promise<StartTripResponse>
  signedIn: boolean
  onSignIn: () => Promise<void>
  onIncident: (incident: Incident | null) => void
  // Called once the incident is attached to the user's account.
  onSaved: (incident: Incident) => void
  // The trip token that authorizes claiming `incident`; see CameraModal.
  tripToken: string | null
  onTripTokenChange: (tripToken: string | null) => void
  // Lets the modal block closing while a press is in flight.
  onBusyChange: (busy: boolean) => void
  incident: Incident | null
}

function Pending({ incident, signedIn, onLogIn }: { incident: Incident; signedIn: boolean; onLogIn: () => void }) {
  const expiresAtMs = incident.expires_at ? Date.parse(incident.expires_at) : null
  const secondsLeft = Math.max(0, ((expiresAtMs ?? 0) - useNow()) / 1000)

  if (expiresAtMs !== null && secondsLeft === 0) {
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
          Pressed at <span className="tabular-nums">{formatClock(Date.parse(incident.trigger_at))}</span>. Footage
          from before your press is being kept.
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

export default function IncidentPanel({
  tripPromise,
  signedIn,
  onSignIn,
  onIncident,
  onSaved,
  tripToken,
  onTripTokenChange,
  onBusyChange,
  incident,
}: Props) {
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

  const saved = incident?.claim_state === 'claimed'

  async function press() {
    setBusy(true)
    onBusyChange(true)
    setSaveError(null)
    const { trip, trip_token: freshTripToken } = await tripPromise
    const reported = await api.reportIncident(trip.id, freshTripToken, signedIn)
    onTripTokenChange(freshTripToken)
    if (reported.claim_state !== 'claimed') storePendingIncident({ incident: reported, tripToken: freshTripToken })
    // The camera was closed while this was in flight: the incident is
    // already persisted above, so skip the remaining state updates
    // rather than touching an unmounted component.
    if (!mounted.current) return
    onIncident(reported)
    if (reported.claim_state === 'claimed') onSaved(reported)
    setBusy(false)
    onBusyChange(false)
    if (reported.claim_state !== 'claimed') setShowLogIn(true)
  }

  // Once the user is logged in, whether here or back from the Google redirect,
  // attach the pending incident to their account.
  useEffect(() => {
    if (!signedIn || !incident || !tripToken || incident.claim_state === 'claimed' || saving.current) return
    if (incident.expires_at !== null && Date.now() >= Date.parse(incident.expires_at)) return
    saving.current = true
    api
      .claimIncident(incident.id, tripToken, signedIn)
      .then((claimed) => {
        clearPendingIncident()
        onIncident(claimed)
        onSaved(claimed)
      })
      .catch(() => setSaveError('Could not save this incident.'))
      .finally(() => {
        saving.current = false
      })
  }, [signedIn, incident, tripToken, onIncident, onSaved, saveAttempt])

  return (
    <div className="mt-1 px-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="max-w-md">
          <p className="font-medium tracking-tight">In an incident?</p>
          <p className="mt-1 text-sm text-muted">
            Saves {formatSpan(CLIP_BEFORE_SECONDS)} of footage before you press and {formatSpan(CLIP_AFTER_SECONDS)}{' '}
            after. {signedIn ? 'It goes straight to your Library.' : "You'll log in to keep it."}
          </p>
        </div>
        <button
          type="button"
          onClick={press}
          // A logged-out save waits for login before another can start; saved ones don't block.
          disabled={busy || (incident !== null && !saved)}
          className="rounded-md bg-rec px-5 py-3 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {busy ? 'Saving...' : saved ? 'Save another' : 'Save recording'}
        </button>
      </div>

      {incident && !saved && !saveError && (
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

      <p className="mt-5 text-xs text-muted">
        This camera may not show your vehicle. Footage gives context, not proof of fault.
      </p>

      {showLogIn && !signedIn && incident && !saved && (
        <SignInDialog
          deadline={incident.expires_at ? Date.parse(incident.expires_at) : undefined}
          onSignIn={onSignIn}
          onClose={() => setShowLogIn(false)}
        />
      )}
    </div>
  )
}

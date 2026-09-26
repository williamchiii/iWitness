import { useEffect, useState } from 'react'
import { isMockAuth } from '../lib/auth'
import { formatDuration } from '../lib/format'
import { useNow } from '../lib/useNow'

interface Props {
  onSignIn: () => Promise<void>
  onClose: () => void
  // When set, the user is saving an incident and must log in before this time.
  deadline?: number
}

function Countdown({ secondsLeft }: { secondsLeft: number }) {
  return (
    <div className="mt-5 rounded-lg border border-line bg-surface p-4">
      <p className="text-xs font-medium uppercase tracking-wider text-muted">Time left to save</p>
      <p className="mt-1 text-4xl font-medium tabular-nums tracking-tight">{formatDuration(secondsLeft)}</p>
    </div>
  )
}

export default function SignInDialog({ onSignIn, onClose, deadline }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const now = useNow()
  const expired = deadline !== undefined && now >= deadline

  // Capture phase, so Esc closes only this box and not the camera popup under it.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== 'Escape') return
      e.stopImmediatePropagation()
      onClose()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose])

  // Stays busy on success: the page is about to leave for Google, or the parent
  // closes this box once the user is signed in.
  async function signIn() {
    setBusy(true)
    setError(null)
    try {
      await onSignIn()
    } catch {
      setError('Could not start Google sign-in. Try again.')
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-[3000] flex items-center justify-center bg-black/20 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="sign-in-title"
        className="w-full max-w-sm rounded-xl border border-line bg-white p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="sign-in-title" className="text-xl font-medium tracking-tight">
          {deadline ? 'Log in to save your footage' : 'Log in'}
        </h2>
        <p className="mt-2 text-sm text-muted">
          {deadline
            ? 'Footage from before your press is being kept. Log in before the timer runs out or it will be deleted.'
            : 'You can watch cameras without an account. Log in to save incident footage to your account.'}
        </p>
        {deadline && <Countdown secondsLeft={Math.max(0, (deadline - now) / 1000)} />}
        <button
          type="button"
          onClick={signIn}
          disabled={busy || expired}
          className="mt-6 w-full rounded-md bg-ink px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-black disabled:opacity-40"
        >
          {busy ? 'Logging in...' : 'Continue with Google'}
        </button>
        {error && <p className="mt-3 text-sm text-rec">{error}</p>}
        <button type="button" onClick={onClose} className="mt-3 w-full py-2 text-sm text-muted hover:text-ink">
          {deadline ? 'Not now' : 'Cancel'}
        </button>
        {isMockAuth && <p className="mt-4 text-xs text-muted">Test mode: no real Google account is used.</p>}
      </div>
    </div>
  )
}

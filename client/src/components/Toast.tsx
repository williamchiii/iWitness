import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

export interface ToastMessage {
  // New id per message, so a repeated message restarts its timer.
  id: number
  title: string
  body?: string
  tone?: 'success' | 'info'
  link?: { to: string; label: string }
}

const VISIBLE_MS = 6000
// Matches the duration-300 transition: slide and fade out, then unmount.
const EXIT_MS = 300

// Top-centre toast that slides down, sits above the header and the camera popup,
// and slides back up when it times out or is closed.
export default function Toast({ toast, onDismiss }: { toast: ToastMessage; onDismiss: () => void }) {
  const [leaving, setLeaving] = useState(false)

  useEffect(() => {
    const timer = setTimeout(() => setLeaving(true), VISIBLE_MS)
    return () => clearTimeout(timer)
  }, [toast.id])

  useEffect(() => {
    if (!leaving) return
    const timer = setTimeout(onDismiss, EXIT_MS)
    return () => clearTimeout(timer)
  }, [leaving, onDismiss])

  return (
    <div
      role="status"
      aria-live="polite"
      className={`fixed left-1/2 top-4 z-[2500] flex w-[calc(100%-2rem)] overflow-hidden max-w-md -translate-x-1/2 items-start gap-3 rounded-xl border border-line bg-white p-4 text-sm shadow-lg transition duration-300 ease-out starting:-translate-y-3 starting:opacity-0 md:top-6 ${
        leaving ? 'pointer-events-none -translate-y-3 opacity-0' : ''
      }`}
    >
      {toast.tone === 'success' && (
        <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-ink text-white">
          <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="m5 12 5 5 9-10" />
          </svg>
        </span>
      )}
      <div className="min-w-0 flex-1">
        <p className="font-medium">{toast.title}</p>
        {toast.body && <p className="mt-0.5 text-muted">{toast.body}</p>}
      </div>
      {toast.link && (
        <Link to={toast.link.to} className="shrink-0 font-medium underline-offset-4 hover:underline">
          {toast.link.label}
        </Link>
      )}
      <button
        type="button"
        onClick={() => setLeaving(true)}
        aria-label="Dismiss"
        className="-mr-1 -mt-0.5 grid size-6 shrink-0 place-items-center rounded-md text-muted transition-colors hover:bg-surface hover:text-ink"
      >
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <path d="M18 6 6 18M6 6l12 12" />
        </svg>
      </button>
      {/* Shrinks to nothing over VISIBLE_MS: shows when the toast will go away. */}
      <span
        aria-hidden="true"
        className="absolute inset-x-0 bottom-0 h-0.5 origin-left bg-ink/25"
        style={{ animation: `toast-countdown ${VISIBLE_MS}ms linear forwards` }}
      />
    </div>
  )
}

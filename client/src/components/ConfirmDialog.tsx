import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { POPUP_BACKDROP, POPUP_BACKDROP_OUT, POPUP_PANEL, POPUP_PANEL_OUT } from '../lib/styles'

interface Props {
  title: string
  body: string
  confirmLabel: string
  // Shown on the confirm button while the action runs.
  busyLabel: string
  busy: boolean
  // Playing its exit animation (see usePopupExit).
  closing: boolean
  error: string | null
  onConfirm: () => void
  onCancel: () => void
  // The button that backs out, when "Cancel" would be confusing.
  cancelLabel?: string
}

// A small "are you sure" box for actions that can't be undone, styled like the
// sign-in box. Rendered on document.body so it sits above whatever opened it.
export default function ConfirmDialog({
  title,
  body,
  confirmLabel,
  busyLabel,
  busy,
  closing,
  error,
  onConfirm,
  onCancel,
  cancelLabel = 'Cancel',
}: Props) {
  // Capture phase, so Esc closes only this box and not the popup under it.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== 'Escape') return
      e.stopImmediatePropagation()
      if (!busy) onCancel()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [busy, onCancel])

  return createPortal(
    <div
      className={`fixed inset-0 z-[3000] flex items-center justify-center bg-black/20 p-4 backdrop-blur-sm ${POPUP_BACKDROP} ${
        closing ? POPUP_BACKDROP_OUT : ''
      }`}
      onClick={(e) => {
        // React events bubble through portals to the component that opened
        // this box; don't let a backdrop click also close that one.
        e.stopPropagation()
        if (!busy) onCancel()
      }}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-body"
        className={`w-full max-w-sm rounded-xl border border-line bg-white p-6 shadow-2xl ${POPUP_PANEL} ${
          closing ? POPUP_PANEL_OUT : ''
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="confirm-title" className="text-xl font-medium tracking-tight">
          {title}
        </h2>
        <p id="confirm-body" className="mt-2 text-sm text-muted">
          {body}
        </p>
        <button
          type="button"
          onClick={onConfirm}
          disabled={busy}
          className="mt-6 w-full rounded-md bg-rec px-4 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          {busy ? busyLabel : confirmLabel}
        </button>
        {error && <p className="mt-3 text-sm text-rec">{error}</p>}
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="mt-3 w-full py-2 text-sm text-muted hover:text-ink disabled:opacity-40"
        >
          {cancelLabel}
        </button>
      </div>
    </div>,
    document.body,
  )
}

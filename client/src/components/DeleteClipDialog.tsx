import { useState } from 'react'
import { ApiError } from '../lib/api'
import type { Incident } from '../lib/api/types'
import { deleteClip } from '../lib/clips'
import { usePopupExit } from '../lib/usePopupExit'
import ConfirmDialog from './ConfirmDialog'

interface Props {
  incident: Incident
  onCancel: () => void
  // The clip is gone from the account (deleted here, or already missing).
  onDeleted: (incident: Incident) => void
}

const DELETE_COPY = {
  title: 'Delete this clip?',
  body: "The video is removed from your Library for good. You can't undo this.",
  confirmLabel: 'Delete clip',
  busyLabel: 'Deleting...',
  cancelLabel: 'Cancel',
  error: 'Could not delete the clip. Try again.',
}

// A clip still recording is cancelled the same way: deleting it stops the
// recording and discards what was kept so far.
const CANCEL_COPY = {
  title: 'Cancel this recording?',
  body: "Recording stops and the footage kept so far is discarded. You can't undo this.",
  confirmLabel: 'Cancel recording',
  busyLabel: 'Cancelling...',
  cancelLabel: 'Keep recording',
  error: 'Could not cancel the recording. Try again.',
}

// Asks before deleting a saved clip for good (or cancelling one still
// recording), then does it. Used by the Library list and the clip popup. The
// box animates out before either callback.
export default function DeleteClipDialog({ incident, onCancel, onDeleted }: Props) {
  // Fixed when the box opens, so the wording doesn't change under the user.
  const [copy] = useState(() => (incident.processing_state === 'recording' ? CANCEL_COPY : DELETE_COPY))
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { closing, close } = usePopupExit()

  async function remove() {
    setDeleting(true)
    setError(null)
    try {
      await deleteClip(incident)
    } catch (e) {
      // 409: the recording just ended and the clip is being put together.
      setError(
        e instanceof ApiError && e.status === 409
          ? 'The clip is being put together right now. Try again in a few seconds.'
          : copy.error,
      )
      setDeleting(false)
      return
    }
    close(() => onDeleted(incident))
  }

  return (
    <ConfirmDialog
      title={copy.title}
      body={copy.body}
      confirmLabel={copy.confirmLabel}
      busyLabel={copy.busyLabel}
      cancelLabel={copy.cancelLabel}
      busy={deleting}
      closing={closing}
      error={error}
      onConfirm={remove}
      onCancel={() => close(onCancel)}
    />
  )
}

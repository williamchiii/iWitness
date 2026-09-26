import { useState } from 'react'
import type { Incident } from '../lib/api/types'
import { deleteClip } from '../lib/clips'
import ConfirmDialog from './ConfirmDialog'

interface Props {
  incident: Incident
  onCancel: () => void
  // The clip is gone from the account (deleted here, or already missing).
  onDeleted: (incident: Incident) => void
}

// Asks before deleting a saved clip for good, then deletes it. Used by the
// Library list and the clip popup.
export default function DeleteClipDialog({ incident, onCancel, onDeleted }: Props) {
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function remove() {
    setDeleting(true)
    setError(null)
    try {
      await deleteClip(incident)
    } catch {
      setError('Could not delete the clip. Try again.')
      setDeleting(false)
      return
    }
    onDeleted(incident)
  }

  return (
    <ConfirmDialog
      title="Delete this clip?"
      body="The video is removed from your Library for good. You can't undo this."
      confirmLabel="Delete clip"
      busyLabel="Deleting..."
      busy={deleting}
      error={error}
      onConfirm={remove}
      onCancel={onCancel}
    />
  )
}

import { api, ApiError } from './api'
import type { Incident, Playback } from './api/types'
import { downloadFile } from './download'
import { formatFileStamp } from './format'

// Signed links are short-lived: refresh one this close to expiring before using it.
const LINK_REFRESH_MARGIN_MS = 30_000

// iwitness_i-95-at-sw-8th-st_2026-09-26_143304.mp4
function downloadName(incident: Incident) {
  const camera = incident.camera_name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
  return `iwitness_${camera}_${formatFileStamp(Date.parse(incident.trigger_at))}.mp4`
}

// Saves a saved clip's file directly, no new tab. Uses `link` unless it is
// missing or about to expire, then asks for a fresh one. Returns the link it
// used, so the caller can reuse it next time.
export async function downloadClip(incident: Incident, link: Playback | null): Promise<Playback> {
  let current = link
  if (!current || Date.now() >= Date.parse(current.expires_at) - LINK_REFRESH_MARGIN_MS) {
    current = await api.getPlayback(incident.id, true)
  }
  await downloadFile(current.download_url, downloadName(incident))
  return current
}

// 404 means the clip is already gone (deleted in another tab, or it expired),
// which counts as deleted.
export async function deleteClip(incident: Incident): Promise<void> {
  try {
    await api.deleteIncident(incident.id, true)
  } catch (e) {
    if (!(e instanceof ApiError && e.status === 404)) throw e
  }
}

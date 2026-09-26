// All cameras are in Miami, so times are shown in Miami's zone whatever the
// viewer's machine is set to. The zone name follows daylight saving: EDT or EST.
const CAMERA_TIME_ZONE = 'America/New_York'

export function formatClock(ms: number) {
  return new Date(ms).toLocaleTimeString('en-US', {
    timeZone: CAMERA_TIME_ZONE,
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    timeZoneName: 'short',
  })
}

export function formatDuration(seconds: number) {
  const s = Math.max(0, Math.round(seconds))
  const pad = (n: number) => String(n).padStart(2, '0')
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${m}:${pad(s % 60)}`
}

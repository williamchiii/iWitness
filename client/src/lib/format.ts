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

// "2026-09-26_143304" in Miami time, for file names.
export function formatFileStamp(ms: number) {
  // sv-SE prints ISO-style "2026-09-26 14:33:04".
  return new Date(ms).toLocaleString('sv-SE', { timeZone: CAMERA_TIME_ZONE }).replace(' ', '_').replaceAll(':', '')
}

// "Sep 26, 2026", in Miami's zone like the clock times.
export function formatDay(ms: number) {
  return new Date(ms).toLocaleDateString('en-US', { timeZone: CAMERA_TIME_ZONE, month: 'short', day: 'numeric', year: 'numeric' })
}

// "7:54:40 to 7:55:55 AM EDT", naming AM/PM and the zone once when both ends share them.
export function formatClockRange(startMs: number, endMs: number) {
  const start = formatClock(startMs)
  const end = formatClock(endMs)
  const suffix = / [AP]M \S+$/
  const shared = start.match(suffix)?.[0]
  return shared && shared === end.match(suffix)?.[0] ? `${start.slice(0, -shared.length)} to ${end}` : `${start} to ${end}`
}

// How long until a time, rounded for reading at a glance: "30 days", "47 hours",
// "12 minutes". Days from 2 days up, hours from 1 hour, minutes below that.
export function formatTimeLeft(ms: number) {
  const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? '' : 's'}`
  const minutes = Math.max(1, Math.ceil(ms / 60_000))
  if (minutes < 60) return plural(minutes, 'minute')
  const hours = Math.round(ms / 3_600_000)
  if (hours < 48) return plural(hours, 'hour')
  return plural(Math.round(ms / 86_400_000), 'day')
}

// 60 -> "1 minute", 120 -> "2 minutes", 15 -> "15 seconds".
export function formatSpan(seconds: number) {
  if (seconds % 60 === 0) {
    const minutes = seconds / 60
    return `${minutes} minute${minutes === 1 ? '' : 's'}`
  }
  return `${seconds} second${seconds === 1 ? '' : 's'}`
}

export function formatDuration(seconds: number) {
  const s = Math.max(0, Math.round(seconds))
  const pad = (n: number) => String(n).padStart(2, '0')
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${m}:${pad(s % 60)}`
}

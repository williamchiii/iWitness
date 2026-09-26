export function formatClock(ms: number) {
  return new Date(ms).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' })
}

export function formatDuration(seconds: number) {
  const s = Math.max(0, Math.round(seconds))
  const pad = (n: number) => String(n).padStart(2, '0')
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${m}:${pad(s % 60)}`
}

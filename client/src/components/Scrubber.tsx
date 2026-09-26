import { useState } from 'react'
import type { KeyboardEvent, PointerEvent } from 'react'

interface Props {
  start: number
  end: number
  current: number
  // Loaded up to here: drawn as a lighter band ahead of the playhead.
  buffered: number
  onSeek: (time: number) => void
  // Label for a point on the timeline, shown while hovering or dragging.
  describe: (time: number) => string
}

const KEY_STEP_SECONDS = 5

// YouTube-style timeline: a thin bar that thickens on hover, a dot that shows
// while hovering or dragging, and a time label above the pointer. Dragging
// only moves the playhead on screen; the video seeks once, on release.
export default function Scrubber({ start, end, current, buffered, onSeek, describe }: Props) {
  const [hoverTime, setHoverTime] = useState<number | null>(null)
  const [dragTime, setDragTime] = useState<number | null>(null)

  const span = Math.max(end - start, 0.001)
  const clamp = (time: number) => Math.min(end, Math.max(start, time))
  const percent = (time: number) => `${((clamp(time) - start) / span) * 100}%`

  function timeAt(e: PointerEvent<HTMLDivElement>) {
    const rect = e.currentTarget.getBoundingClientRect()
    return start + Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)) * span
  }

  function onPointerDown(e: PointerEvent<HTMLDivElement>) {
    e.currentTarget.setPointerCapture(e.pointerId)
    setDragTime(timeAt(e))
  }

  function onPointerMove(e: PointerEvent<HTMLDivElement>) {
    const time = timeAt(e)
    setHoverTime(time)
    if (dragTime !== null) setDragTime(time)
  }

  function onPointerUp(e: PointerEvent<HTMLDivElement>) {
    if (dragTime === null) return
    onSeek(timeAt(e))
    setDragTime(null)
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const target =
      e.key === 'ArrowLeft' ? current - KEY_STEP_SECONDS
      : e.key === 'ArrowRight' ? current + KEY_STEP_SECONDS
      : e.key === 'Home' ? start
      : e.key === 'End' ? end
      : null
    if (target === null) return
    e.preventDefault()
    onSeek(clamp(target))
  }

  const dragging = dragTime !== null
  const position = dragTime ?? current
  const labelTime = dragTime ?? hoverTime

  return (
    <div
      role="slider"
      tabIndex={0}
      aria-label="Scrub back through the recording"
      aria-valuemin={start}
      aria-valuemax={end}
      aria-valuenow={position}
      aria-valuetext={describe(position)}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={() => setDragTime(null)}
      onPointerLeave={() => setHoverTime(null)}
      onKeyDown={onKeyDown}
      className="group relative flex h-4 cursor-pointer touch-none items-center outline-none"
    >
      {labelTime !== null && (
        <span
          className="pointer-events-none absolute bottom-full mb-1 -translate-x-1/2 whitespace-nowrap rounded-md border border-line bg-white px-2 py-1 text-xs font-medium tabular-nums text-ink shadow-sm"
          // Kept inside the bar at both ends, like YouTube's preview label.
          style={{ left: `clamp(5.5rem, ${percent(labelTime)}, calc(100% - 5.5rem))` }}
        >
          {describe(labelTime)}
        </span>
      )}
      <div
        className={`relative w-full rounded-full bg-ink/10 transition-[height] duration-150 group-hover:h-1.5 group-focus-visible:h-1.5 ${
          dragging ? 'h-1.5' : 'h-1'
        }`}
      >
        <div className="absolute inset-y-0 left-0 rounded-full bg-ink/20" style={{ width: percent(buffered) }} />
        <div className="absolute inset-y-0 left-0 rounded-full bg-rec" style={{ width: percent(position) }} />
        <div
          className={`absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-rec ring-2 ring-white transition-transform duration-150 group-hover:scale-100 group-focus-visible:scale-100 ${
            dragging ? 'scale-100' : 'scale-0'
          }`}
          style={{ left: percent(position) }}
        />
      </div>
    </div>
  )
}

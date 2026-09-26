import Hls from 'hls.js'
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { formatClock, formatDuration } from '../lib/format'

type Mode = 'live' | 'playback'

interface Timeline {
  start: number
  end: number
  current: number
  // Wall-clock ms at media time 0, from EXT-X-PROGRAM-DATE-TIME. Null if the stream has none.
  epochMs: number | null
}

function Label({ children }: { children: ReactNode }) {
  return (
    <span className="flex items-center gap-1.5 rounded bg-white px-2 py-1 text-xs font-medium text-ink">
      {children}
    </span>
  )
}

interface Props {
  src: string
  labels: string[]
}

export default function Player({ src, labels }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const hlsRef = useRef<Hls | null>(null)
  const [mode, setMode] = useState<Mode>('live')
  const [timeline, setTimeline] = useState<Timeline | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const video = videoRef.current!
    if (Hls.isSupported()) {
      const hls = new Hls()
      hlsRef.current = hls
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (data.fatal) setFailed(true)
      })
      hls.loadSource(src)
      hls.attachMedia(video)
      return () => {
        hls.destroy()
        hlsRef.current = null
      }
    }
    // Safari without MSE plays HLS natively.
    video.src = src
    return () => {
      video.removeAttribute('src')
      video.load()
    }
  }, [src])

  useEffect(() => {
    const video = videoRef.current!
    function update() {
      const { seekable } = video
      if (!seekable.length) return
      const date = hlsRef.current?.playingDate
      setTimeline({
        start: seekable.start(0),
        end: seekable.end(seekable.length - 1),
        current: video.currentTime,
        epochMs: date ? date.getTime() - video.currentTime * 1000 : null,
      })
    }
    const events = ['timeupdate', 'seeked', 'durationchange', 'progress']
    for (const event of events) video.addEventListener(event, update)
    return () => {
      for (const event of events) video.removeEventListener(event, update)
    }
  }, [])

  function goLive() {
    const video = videoRef.current!
    const { seekable } = video
    const edge = hlsRef.current?.liveSyncPosition ?? (seekable.length ? seekable.end(seekable.length - 1) : null)
    if (edge != null) video.currentTime = edge
    video.play().catch(() => {})
    setMode('live')
  }

  function clockAt(time: number) {
    return timeline?.epochMs != null ? formatClock(timeline.epochMs + time * 1000) : null
  }

  const tab = (active: boolean) =>
    `px-4 py-1.5 text-sm transition-colors ${active ? 'bg-ink text-white' : 'text-muted hover:text-ink'}`

  return (
    <div>
      <div className="relative aspect-video bg-black">
        <video
          ref={videoRef}
          className="size-full object-contain"
          autoPlay
          muted
          playsInline
          onError={() => setFailed(true)}
        />
        <div className="absolute left-3 top-3">
          {mode === 'live' ? (
            <Label>
              <span className="size-1.5 rounded-full bg-rec" /> Live
            </Label>
          ) : (
            timeline && <Label>{formatDuration(timeline.end - timeline.current)} behind live</Label>
          )}
        </div>
        <div className="absolute right-3 top-3 flex gap-2">
          {labels.map((label) => (
            <Label key={label}>{label}</Label>
          ))}
        </div>
        {failed && (
          <div className="absolute inset-0 grid place-items-center bg-black/80 text-sm text-white/80">
            Video unavailable. Close and reopen the camera to try again.
          </div>
        )}
      </div>

      <div className="flex items-center gap-4 px-6 pt-4">
        <div className="flex overflow-hidden rounded-md border border-line">
          <button type="button" onClick={goLive} className={tab(mode === 'live')}>
            Live
          </button>
          <button type="button" onClick={() => setMode('playback')} className={tab(mode === 'playback')}>
            Playback
          </button>
        </div>
        {timeline && <span className="ml-auto text-sm tabular-nums text-muted">{clockAt(timeline.current)}</span>}
      </div>

      {mode === 'playback' && timeline && (
        <div className="px-6 pt-4">
          <input
            type="range"
            aria-label="Scrub back through the recording"
            min={timeline.start}
            max={timeline.end}
            step={0.1}
            value={timeline.current}
            onChange={(e) => {
              videoRef.current!.currentTime = Number(e.target.value)
            }}
            className="w-full accent-ink"
          />
          <div className="mt-1 flex justify-between text-xs tabular-nums text-muted">
            <span>{clockAt(timeline.start) ?? `${formatDuration(timeline.end - timeline.start)} ago`}</span>
            <button type="button" onClick={goLive} className="hover:text-ink">
              Now
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

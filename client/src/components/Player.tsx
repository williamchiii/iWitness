import Hls from 'hls.js'
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { formatClock, formatDuration } from '../lib/format'
import Scrubber from './Scrubber'

interface Timeline {
  start: number
  end: number
  // Where "live" is: hls.js keeps a few segments behind the newest one.
  liveEdge: number
  current: number
  buffered: number
  // Wall-clock ms at media time 0, from EXT-X-PROGRAM-DATE-TIME. Null if the stream has none.
  epochMs: number | null
}

// Within this many seconds of the live edge counts as live.
const LIVE_SLACK_SECONDS = 5

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

// One YouTube-style timeline over the camera's loop buffer: drag back to watch
// earlier footage, press Live to jump back to now.
export default function Player({ src, labels }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const hlsRef = useRef<Hls | null>(null)
  const [timeline, setTimeline] = useState<Timeline | null>(null)
  const [paused, setPaused] = useState(false)
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
      setPaused(video.paused)
      const { seekable } = video
      if (!seekable.length) return
      const end = seekable.end(seekable.length - 1)
      const date = hlsRef.current?.playingDate
      let buffered = video.currentTime
      for (let i = 0; i < video.buffered.length; i++) {
        if (video.buffered.start(i) <= video.currentTime + 0.5) buffered = Math.max(buffered, video.buffered.end(i))
      }
      setTimeline({
        start: seekable.start(0),
        end,
        liveEdge: Math.min(hlsRef.current?.liveSyncPosition ?? end, end),
        current: video.currentTime,
        buffered,
        epochMs: date ? date.getTime() - video.currentTime * 1000 : null,
      })
    }
    const events = ['timeupdate', 'seeked', 'durationchange', 'progress', 'play', 'pause']
    for (const event of events) video.addEventListener(event, update)
    return () => {
      for (const event of events) video.removeEventListener(event, update)
    }
  }, [])

  function seek(time: number) {
    videoRef.current!.currentTime = time
    // Show the new position right away instead of waiting for the next timeupdate.
    setTimeline((t) => t && { ...t, current: time })
  }

  function goLive() {
    if (timeline) seek(timeline.liveEdge)
    videoRef.current!.play().catch(() => {})
  }

  function togglePlay() {
    const video = videoRef.current!
    if (video.paused) video.play().catch(() => {})
    else video.pause()
  }

  function clockAt(time: number) {
    return timeline?.epochMs != null ? formatClock(timeline.epochMs + time * 1000) : null
  }

  // Time label for any point on the timeline: recording clock, and how far behind live.
  function describe(time: number) {
    const behind = timeline ? Math.max(0, timeline.liveEdge - time) : 0
    const clock = clockAt(time)
    const offset = behind < LIVE_SLACK_SECONDS ? 'Live' : `-${formatDuration(behind)}`
    return clock ? `${clock} · ${offset}` : offset
  }

  const isLive = timeline !== null && timeline.liveEdge - timeline.current <= LIVE_SLACK_SECONDS
  const max = timeline ? Math.max(timeline.liveEdge, timeline.current) : 0

  return (
    <div>
      <div className="relative aspect-video bg-black">
        <video
          ref={videoRef}
          className="size-full object-contain"
          autoPlay
          muted
          playsInline
          onClick={togglePlay}
          onError={() => setFailed(true)}
        />
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

      <div className="px-6 pt-2.5 text-ink">
        {timeline && (
          <Scrubber
            start={timeline.start}
            end={max}
            current={timeline.current}
            buffered={timeline.buffered}
            onSeek={seek}
            describe={describe}
          />
        )}

        <div className="mt-1 flex h-6 items-center gap-4">
          <button
            type="button"
            onClick={togglePlay}
            aria-label={paused ? 'Play' : 'Pause'}
            className="-ml-1.5 grid h-6 w-8 place-items-center rounded-md transition-colors hover:bg-surface"
          >
            {paused ? (
              <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true">
                <path d="M7 4.5v15a1 1 0 0 0 1.5.86l12.5-7.5a1 1 0 0 0 0-1.72L8.5 3.64A1 1 0 0 0 7 4.5Z" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true">
                <rect x="6" y="4" width="4" height="16" rx="1" />
                <rect x="14" y="4" width="4" height="16" rx="1" />
              </svg>
            )}
          </button>
          <button
            type="button"
            onClick={goLive}
            aria-label={isLive ? 'Watching live' : 'Jump to live'}
            className="flex h-6 items-center gap-2 rounded-md px-2 text-sm font-medium transition-colors hover:bg-surface"
          >
            <span className={`size-2 rounded-full ${isLive ? 'bg-rec' : 'bg-ink/25'}`} />
            <span className={isLive ? 'text-ink' : 'text-muted'}>Live</span>
          </button>
          {timeline && (
            <span className="ml-auto text-sm tabular-nums text-muted">
              {clockAt(timeline.current)}
              {!isLive && <span className="text-ink/40"> · -{formatDuration(timeline.liveEdge - timeline.current)}</span>}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

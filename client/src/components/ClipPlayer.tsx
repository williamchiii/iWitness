import Hls from 'hls.js'
import { useEffect, useRef, useState } from 'react'
import { formatClock, formatDuration } from '../lib/format'
import Scrubber from './Scrubber'

interface Props {
  src: string
  // Wall-clock ms of the clip's first frame, used until the stream's own
  // EXT-X-PROGRAM-DATE-TIME is known.
  startMs: number
  // When save was pressed: ticked on the timeline, and every time label says
  // how far before or after it the footage is.
  triggerMs: number
  labels: string[]
}

interface Timeline {
  current: number
  duration: number
  buffered: number
  epochMs: number
}

// Player for a saved clip: a fixed recording, so no live edge. Otherwise the
// same controls as the live camera player.
export default function ClipPlayer({ src, startMs, triggerMs, labels }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const hlsRef = useRef<Hls | null>(null)
  const [timeline, setTimeline] = useState<Timeline | null>(null)
  const [paused, setPaused] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const video = videoRef.current!
    // The backend serves saved clips as MP4, which the video element plays by itself.
    const isHls = new URL(src, window.location.href).pathname.endsWith('.m3u8')
    if (isHls && Hls.isSupported()) {
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
    // MP4, or HLS on Safari without MSE, which plays it natively.
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
      if (!Number.isFinite(video.duration)) return
      let buffered = video.currentTime
      for (let i = 0; i < video.buffered.length; i++) {
        if (video.buffered.start(i) <= video.currentTime + 0.5) buffered = Math.max(buffered, video.buffered.end(i))
      }
      const date = hlsRef.current?.playingDate
      setTimeline({
        current: video.currentTime,
        duration: video.duration,
        buffered,
        epochMs: date ? date.getTime() - video.currentTime * 1000 : startMs,
      })
    }
    const events = ['timeupdate', 'seeked', 'durationchange', 'progress', 'play', 'pause', 'loadedmetadata']
    for (const event of events) video.addEventListener(event, update)
    return () => {
      for (const event of events) video.removeEventListener(event, update)
    }
  }, [startMs])

  function seek(time: number) {
    videoRef.current!.currentTime = time
    setTimeline((t) => t && { ...t, current: time })
  }

  function togglePlay() {
    const video = videoRef.current!
    if (video.paused) video.play().catch(() => {})
    else video.pause()
  }

  const epochMs = timeline?.epochMs ?? startMs
  const triggerTime = (triggerMs - epochMs) / 1000

  // "7:55:05 AM EDT · 0:35 before press"
  function describe(time: number) {
    const offset = time - triggerTime
    const relative =
      Math.abs(offset) < 0.5
        ? 'when you pressed save'
        : `${formatDuration(Math.abs(offset))} ${offset < 0 ? 'before' : 'after'} press`
    return `${formatClock(epochMs + time * 1000)} · ${relative}`
  }

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
            <span key={label} className="rounded bg-white px-2 py-1 text-xs font-medium text-ink">
              {label}
            </span>
          ))}
        </div>
        {failed && (
          <div className="absolute inset-0 grid place-items-center bg-black/80 px-6 text-center text-sm text-white/80">
            This clip can't be played right now.
          </div>
        )}
      </div>

      <div className="px-6 pt-2.5 text-ink">
        {timeline && (
          <Scrubber
            start={0}
            end={timeline.duration}
            current={timeline.current}
            buffered={timeline.buffered}
            onSeek={seek}
            describe={describe}
            marks={[{ time: triggerTime, label: 'You pressed save here' }]}
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
          {timeline && (
            <span className="text-sm tabular-nums text-muted">
              {formatDuration(timeline.current)} / {formatDuration(timeline.duration)}
            </span>
          )}
          {timeline && (
            <span className="ml-auto text-sm tabular-nums text-muted">{formatClock(epochMs + timeline.current * 1000)}</span>
          )}
        </div>
      </div>
    </div>
  )
}

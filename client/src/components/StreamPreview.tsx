import Hls from 'hls.js'
import { useEffect, useRef, useState } from 'react'
import { CAMERA_SVG } from '../lib/icons'

interface Props {
  src: string
  label?: string
}

// A frozen frame from the stream for the camera list: fetch just enough to decode one
// frame, then stop loading. The video never plays, so it can't pass for a live feed.
export default function StreamPreview({ src, label }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const video = videoRef.current!
    if (Hls.isSupported()) {
      // Lowest rendition and a tiny buffer: a thumbnail needs one fragment.
      const hls = new Hls({ startLevel: 0, maxBufferLength: 2, maxMaxBufferLength: 2 })
      const onFrame = () => {
        hls.stopLoad()
        setReady(true)
      }
      video.addEventListener('loadeddata', onFrame, { once: true })
      hls.loadSource(src)
      hls.attachMedia(video)
      return () => {
        video.removeEventListener('loadeddata', onFrame)
        hls.destroy()
      }
    }
    // Safari without MSE plays HLS natively.
    const onFrame = () => setReady(true)
    video.addEventListener('loadeddata', onFrame, { once: true })
    video.src = src
    return () => {
      video.removeEventListener('loadeddata', onFrame)
      video.removeAttribute('src')
      video.load()
    }
  }, [src])

  return (
    <div className="relative grid aspect-video w-56 shrink-0 place-items-center overflow-hidden rounded-lg bg-black/5 text-neutral-500">
      {/* Shown until the frame decodes, and kept if the stream fails. */}
      <span dangerouslySetInnerHTML={{ __html: CAMERA_SVG }} />
      <video
        ref={videoRef}
        muted
        playsInline
        preload="auto"
        aria-hidden
        className={`absolute inset-0 size-full object-cover transition-opacity duration-300 ${
          ready ? 'opacity-100' : 'opacity-0'
        }`}
      />
      {ready && label && (
        <span className="absolute bottom-1.5 left-1.5 rounded bg-white/85 px-1.5 py-0.5 text-[10px] font-medium text-ink">
          {label}
        </span>
      )}
    </div>
  )
}

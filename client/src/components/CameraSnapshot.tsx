import { useState } from 'react'
import { CAMERA_SVG } from '../lib/icons'

interface Props {
  src: string
}

// The camera's latest still from FDOT (updated about every 2 minutes), for the
// camera list. Labeled so it can't pass for the live feed.
export default function CameraSnapshot({ src }: Props) {
  const [ready, setReady] = useState(false)

  return (
    <div className="relative grid aspect-video w-56 shrink-0 place-items-center overflow-hidden rounded-lg bg-black/5 text-neutral-500">
      {/* Shown until the image loads, and kept if it fails. */}
      <span dangerouslySetInnerHTML={{ __html: CAMERA_SVG }} />
      <img
        src={src}
        alt=""
        loading="lazy"
        onLoad={() => setReady(true)}
        className={`absolute inset-0 size-full object-cover transition-opacity duration-300 ${
          ready ? 'opacity-100' : 'opacity-0'
        }`}
      />
      {ready && (
        <span className="absolute bottom-1.5 left-1.5 rounded bg-white/85 px-1.5 py-0.5 text-[10px] font-medium text-ink">
          Snapshot
        </span>
      )}
    </div>
  )
}

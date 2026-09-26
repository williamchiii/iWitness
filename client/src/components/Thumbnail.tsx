import { useState } from 'react'
import type { ReactNode } from 'react'
import { CAMERA_SVG } from '../lib/icons'

interface Props {
  // The image, or null to show the placeholder.
  src: string | null
  // Small tag on the loaded image, so a still can't pass for live video.
  label: string
  // Width classes; the box is always 16:9.
  className?: string
  // Shown centered over the image or placeholder, e.g. a play button or a status.
  children?: ReactNode
}

// A still in a rounded 16:9 box, used by the camera list and the Library. The
// camera icon stands in until the image loads, and stays if it fails.
export default function Thumbnail({ src, label, className = '', children }: Props) {
  // Which src loaded or failed, so a new src starts fresh.
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null)
  const [failedSrc, setFailedSrc] = useState<string | null>(null)
  const failed = src !== null && failedSrc === src
  const shown = src !== null && loadedSrc === src && !failed

  return (
    <div
      className={`relative grid aspect-video shrink-0 place-items-center overflow-hidden rounded-lg bg-black/5 text-neutral-500 ${className}`}
    >
      {!children && !shown && <span dangerouslySetInnerHTML={{ __html: CAMERA_SVG }} />}
      {src !== null && !failed && (
        <img
          src={src}
          alt=""
          loading="lazy"
          onLoad={() => setLoadedSrc(src)}
          onError={() => setFailedSrc(src)}
          className={`absolute inset-0 size-full object-cover transition-opacity duration-300 ${
            shown ? 'opacity-100' : 'opacity-0'
          }`}
        />
      )}
      {children && <div className="relative">{children}</div>}
      {shown && (
        <span className="absolute bottom-1.5 left-1.5 rounded bg-white/85 px-1.5 py-0.5 text-[10px] font-medium text-ink">
          {label}
        </span>
      )}
    </div>
  )
}

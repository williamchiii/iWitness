import type { Camera } from '../lib/cameras'
import { CAMERA_SVG } from '../lib/icons'

interface Props {
  camera: Camera
  number: number
  active: boolean
  onHover: (id: string | null) => void
  onSelect: (id: string) => void
}

export default function CameraCard({ camera, number, active, onHover, onSelect }: Props) {
  return (
    <button
      type="button"
      onClick={() => onSelect(camera.id)}
      onMouseEnter={() => onHover(camera.id)}
      onMouseLeave={() => onHover(null)}
      className={`glass-card flex w-full gap-5 rounded-xl border p-3 text-left transition-colors ${
        active ? 'border-ink' : 'border-white/70 hover:border-white'
      }`}
    >
      {/* Feed placeholder until live video is wired up. */}
      <div
        className="grid aspect-video w-56 shrink-0 place-items-center rounded-lg bg-black/5 text-neutral-500"
        dangerouslySetInnerHTML={{ __html: CAMERA_SVG }}
      />
      <div className="flex min-w-0 flex-col py-1">
        <p className="text-xs font-medium uppercase tracking-wider text-muted">Cam {number}</p>
        <p className="mt-1 text-lg font-medium tracking-tight">{camera.name}</p>
        <p className="text-sm text-muted">{camera.direction}</p>
        <p className="mt-auto flex items-center gap-2 text-xs text-muted">
          <span className="size-1.5 rounded-full bg-rec" />
          Recording
        </p>
      </div>
    </button>
  )
}

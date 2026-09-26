import type { Camera } from '../lib/cameras'
import CameraCard from './CameraCard'

interface Props {
  cameras: Camera[]
  activeId: string | null
  onHover: (id: string | null) => void
  onSelect: (id: string) => void
}

export default function CameraList({ cameras, activeId, onHover, onSelect }: Props) {
  return (
    <ul className="space-y-3">
      {cameras.map((camera, i) => (
        <li key={camera.id}>
          <CameraCard
            camera={camera}
            number={i + 1}
            active={activeId === camera.id}
            onHover={onHover}
            onSelect={onSelect}
          />
        </li>
      ))}
    </ul>
  )
}

import { cameraNumber } from '../lib/cameras'
import type { Camera } from '../lib/cameras'
import CameraCard from './CameraCard'

interface Props {
  cameras: Camera[]
  // Search rank of each matching camera (0 is best). Cameras not in it stay mounted but hidden,
  // and matches are reordered with CSS order, so preview frames are never reloaded.
  ranks: Map<string, number>
  activeId: string | null
  onHover: (id: string | null) => void
  onSelect: (id: string) => void
}

export default function CameraList({ cameras, ranks, activeId, onHover, onSelect }: Props) {
  return (
    <ul className="flex flex-col gap-3">
      {cameras.map((camera) => (
        <li key={camera.id} hidden={!ranks.has(camera.id)} style={{ order: ranks.get(camera.id) }}>
          <CameraCard
            camera={camera}
            number={cameraNumber(camera.id)}
            active={activeId === camera.id}
            onHover={onHover}
            onSelect={onSelect}
          />
        </li>
      ))}
    </ul>
  )
}

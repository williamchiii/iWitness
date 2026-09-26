import { cameraNumber } from '../lib/cameras'
import type { Camera } from '../lib/cameras'
import CameraCard from './CameraCard'

interface Props {
  cameras: Camera[]
  // Cameras matching the search. The rest stay mounted but hidden, so their preview frames are kept.
  matchIds: Set<string>
  activeId: string | null
  onHover: (id: string | null) => void
  onSelect: (id: string) => void
}

export default function CameraList({ cameras, matchIds, activeId, onHover, onSelect }: Props) {
  return (
    <ul className="space-y-3">
      {cameras.map((camera) => (
        <li key={camera.id} hidden={!matchIds.has(camera.id)}>
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

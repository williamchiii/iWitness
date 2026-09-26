import L from 'leaflet'
import type { LatLngBounds } from 'leaflet'
import { useEffect, useMemo, useRef } from 'react'
import { MapContainer, Marker, TileLayer, Tooltip, ZoomControl, useMap } from 'react-leaflet'
import type { Camera } from '../lib/cameras'
import { CAMERA_SVG } from '../lib/icons'

function pin(active: boolean) {
  return L.divIcon({
    className: '',
    html: `<div class="cam-pin${active ? ' cam-pin-active' : ''}">${CAMERA_SVG}</div>`,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
  })
}

const PIN = pin(false)
const PIN_ACTIVE = pin(true)
const PADDING: [number, number] = [64, 64]

// Fly to the opened camera; back out to all cameras when it closes.
function Focus({ camera, bounds }: { camera: Camera | undefined; bounds: LatLngBounds }) {
  const map = useMap()
  const hasOpened = useRef(false)
  useEffect(() => {
    if (camera) {
      hasOpened.current = true
      map.flyTo([camera.lat, camera.lng], 14, { duration: 0.8 })
    } else if (hasOpened.current) {
      map.flyToBounds(bounds, { padding: PADDING, duration: 0.8 })
    }
  }, [map, camera, bounds])
  return null
}

interface Props {
  cameras: Camera[]
  activeId: string | null
  selected: Camera | undefined
  onHover: (id: string | null) => void
  onSelect: (id: string) => void
}

export default function CameraMap({ cameras, activeId, selected, onHover, onSelect }: Props) {
  const bounds = useMemo(() => L.latLngBounds(cameras.map((c) => [c.lat, c.lng])), [cameras])

  return (
    <MapContainer bounds={bounds} boundsOptions={{ padding: PADDING }} zoomControl={false} className="size-full">
      <TileLayer
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        maxZoom={19}
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      />
      <ZoomControl position="bottomright" />
      {cameras.map((camera, i) => (
        <Marker
          key={camera.id}
          position={[camera.lat, camera.lng]}
          icon={activeId === camera.id ? PIN_ACTIVE : PIN}
          zIndexOffset={activeId === camera.id ? 1000 : 0}
          eventHandlers={{
            click: () => onSelect(camera.id),
            mouseover: () => onHover(camera.id),
            mouseout: () => onHover(null),
          }}
        >
          <Tooltip direction="top" offset={[0, -18]} className="cam-tooltip">
            Cam {i + 1}: {camera.name}
          </Tooltip>
        </Marker>
      ))}
      <Focus camera={selected} bounds={bounds} />
    </MapContainer>
  )
}

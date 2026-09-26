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
const PADDING = 64
const FOCUS_ZOOM = 14
// Width the floating camera list covers on the left at md and up: 36rem pane + 24px inset + 24px gap.
const PANE_PX = 624

// True once the list stops stacking above the map and starts floating over it.
function paneOverlaps() {
  return window.matchMedia('(min-width: 768px)').matches
}

function fitOptions() {
  return {
    paddingTopLeft: [paneOverlaps() ? PANE_PX : PADDING, PADDING] as [number, number],
    paddingBottomRight: [PADDING, PADDING] as [number, number],
  }
}

// Fly to the opened camera; back out to all cameras when it closes.
// Both keep the pins in the strip of map the glass pane does not cover.
function Focus({ camera, bounds }: { camera: Camera | undefined; bounds: LatLngBounds }) {
  const map = useMap()
  const hasOpened = useRef(false)
  useEffect(() => {
    if (camera) {
      hasOpened.current = true
      const point = map.project([camera.lat, camera.lng], FOCUS_ZOOM)
      const shift = paneOverlaps() ? PANE_PX / 2 : 0
      map.flyTo(map.unproject(point.subtract([shift, 0]), FOCUS_ZOOM), FOCUS_ZOOM, { duration: 0.8 })
    } else if (hasOpened.current) {
      map.flyToBounds(bounds, { ...fitOptions(), duration: 0.8 })
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
    <MapContainer bounds={bounds} boundsOptions={fitOptions()} zoomControl={false} className="size-full">
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

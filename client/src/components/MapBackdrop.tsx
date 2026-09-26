import { MapContainer, TileLayer } from 'react-leaflet'

// South Florida from Broward down to Homestead, so the coast frames the content.
const CENTER: [number, number] = [25.82, -80.3]
const ZOOM = 10

// A still, faded map of South Florida behind a page's content: every
// interaction is off, so it reads as a backdrop rather than a map to use.
export default function MapBackdrop() {
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-0">
      <MapContainer
        center={CENTER}
        zoom={ZOOM}
        zoomControl={false}
        dragging={false}
        scrollWheelZoom={false}
        doubleClickZoom={false}
        touchZoom={false}
        boxZoom={false}
        keyboard={false}
        className="map-backdrop size-full"
      >
        <TileLayer
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          maxZoom={19}
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        />
      </MapContainer>
    </div>
  )
}

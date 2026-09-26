import { MapContainer, TileLayer } from 'react-leaflet'

// Downtown Miami, where the cameras are, with Doral, Coral Gables, Miami Beach
// and Key Biscayne around the panel.
const CENTER: [number, number] = [25.79, -80.21]
const ZOOM = 12

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

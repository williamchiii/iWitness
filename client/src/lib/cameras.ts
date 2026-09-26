import type { Camera as ListedCamera, SourceType } from './api/types'

// Where a camera is and what people call the area around it.
export interface CameraPlace {
  id: string
  name: string
  direction: string
  // Nearby areas and landmarks people might search for.
  keywords: string[]
  lat: number
  lng: number
}

// A camera the backend lists, placed on the map.
export interface Camera extends CameraPlace {
  source_type: SourceType
  recording: boolean
}

// The five FL511 cameras on I-95 through downtown Miami and Brickell, north to
// south, from FDOT's FL511_Traffic_Cameras layer (ID, description, direction,
// position as listed there). The number in each id is the FL511 camera ID.
// The backend's camera table has the same ids (server/migrations/003_i95_cameras.sql).
export const cameraPlaces: CameraPlace[] = [
  { id: 'fl511-760', name: 'I-95 at NW 13th St', direction: 'Southbound', keywords: ['Downtown', 'Overtown'], lat: 25.78645, lng: -80.20316 },
  { id: 'fl511-733', name: 'I-95 at NW 6th St', direction: 'Northbound', keywords: ['Downtown', 'Overtown'], lat: 25.7796, lng: -80.20012 },
  { id: 'fl511-1329', name: 'I-95 at SW 8th St', direction: 'Southbound', keywords: ['Brickell', 'Calle Ocho', 'Little Havana', 'Miami River'], lat: 25.76609, lng: -80.20063 },
  { id: 'fl511-1428', name: 'I-95 at SW 20th Rd', direction: 'Southbound', keywords: ['Brickell', 'The Roads'], lat: 25.75612, lng: -80.20084 },
  { id: 'fl511-736', name: 'I-95 at SW 26th Rd', direction: 'Southbound', keywords: ['Brickell', 'The Roads', 'Rickenbacker', 'US-1'], lat: 25.75234, lng: -80.20623 },
]

// The backend decides which cameras exist, what they're called, and whether they're
// recording; this file adds where they are. A listed camera with no place here
// can't go on the map, so it's left out.
export function placeCameras(listed: ListedCamera[]): Camera[] {
  return cameraPlaces.flatMap((place) => {
    const camera = listed.find((c) => c.id === place.id)
    if (!camera) return []
    return [{ ...place, name: camera.name, direction: camera.location, source_type: camera.source_type, recording: camera.recording }]
  })
}

// Cam numbers follow the list order above and stay fixed while the list is filtered.
export function cameraNumber(id: string) {
  return cameraPlaces.findIndex((c) => c.id === id) + 1
}

// Public live test stream (Unified Streaming demo) with a burned-in clock and a
// ~10 min rewind window. Stands in for the camera list's preview frames.
export const SAMPLE_STREAM_URL = 'https://demo.unified-streaming.com/k8s/live/stable/live.isml/.m3u8'

export interface Camera {
  id: string
  name: string
  direction: string
  // Nearby areas and landmarks people might search for.
  keywords: string[]
  lat: number
  lng: number
}

// The five FL511 cameras on I-95 through downtown Miami and Brickell, north to
// south, from FDOT's FL511_Traffic_Cameras layer (ID, description, direction,
// position as listed there). The number in each id is the FL511 camera ID.
// TODO: confirm each streams continuous video and is covered by the FDOT
// permission in CLAUDE.local.md, then load from the API.
export const cameras: Camera[] = [
  { id: 'fl511-760', name: 'I-95 at NW 13th St', direction: 'Southbound', keywords: ['Downtown', 'Overtown'], lat: 25.78645, lng: -80.20316 },
  { id: 'fl511-733', name: 'I-95 at NW 6th St', direction: 'Northbound', keywords: ['Downtown', 'Overtown'], lat: 25.7796, lng: -80.20012 },
  { id: 'fl511-1329', name: 'I-95 at SW 8th St', direction: 'Southbound', keywords: ['Brickell', 'Calle Ocho', 'Little Havana', 'Miami River'], lat: 25.76609, lng: -80.20063 },
  { id: 'fl511-1428', name: 'I-95 at SW 20th Rd', direction: 'Southbound', keywords: ['Brickell', 'The Roads'], lat: 25.75612, lng: -80.20084 },
  { id: 'fl511-736', name: 'I-95 at SW 26th Rd', direction: 'Southbound', keywords: ['Brickell', 'The Roads', 'Rickenbacker', 'US-1'], lat: 25.75234, lng: -80.20623 },
]

// Cam numbers follow the list order above and stay fixed while the list is filtered.
export function cameraNumber(id: string) {
  return cameras.findIndex((c) => c.id === id) + 1
}

// Public live test stream (Unified Streaming demo) with a burned-in clock and a
// ~10 min rewind window. Stands in for a camera's loop buffer until the backend serves one.
export const SAMPLE_STREAM_URL = 'https://demo.unified-streaming.com/k8s/live/stable/live.isml/.m3u8'

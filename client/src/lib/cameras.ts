export interface Camera {
  id: string
  name: string
  direction: string
  lat: number
  lng: number
}

// Placeholders: real FL511 I-95 camera names and positions in Miami-Dade, but
// not necessarily the five the team has permission for.
// TODO: swap in the five permitted cameras from CLAUDE.local.md, then load from the API.
export const cameras: Camera[] = [
  { id: 'cam-ives-dairy', name: 'I-95 at Ives Dairy Rd', direction: 'Northbound', lat: 25.96348, lng: -80.16497 },
  { id: 'cam-nw-151', name: 'I-95 at NW 151st St', direction: 'Southbound', lat: 25.91286, lng: -80.21041 },
  { id: 'cam-nw-103', name: 'I-95 at NW 103rd St', direction: 'Southbound', lat: 25.86894, lng: -80.20878 },
  { id: 'cam-nw-62', name: 'I-95 at NW 62nd St', direction: 'Southbound', lat: 25.83252, lng: -80.20621 },
  { id: 'cam-sw-8', name: 'I-95 at SW 8th St', direction: 'Southbound', lat: 25.76609, lng: -80.20063 },
]

// Public live test stream (Unified Streaming demo) with a burned-in clock and a
// ~10 min rewind window. Stands in for a camera's loop buffer until the backend serves one.
export const SAMPLE_STREAM_URL = 'https://demo.unified-streaming.com/k8s/live/stable/live.isml/.m3u8'

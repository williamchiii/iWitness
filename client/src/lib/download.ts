// Saves a clip straight to disk: fetch it, then hand the bytes to a same-origin
// blob link, so the page never navigates and the browser uses our file name
// (a cross-origin link would ignore the `download` attribute). The download URL
// must allow CORS or be same-origin; Supabase signed URLs and the /api proxy do.
//
// The real backend's download_url is an MP4. The mock's is an HLS playlist, so
// a playlist is stitched into one file here: MP4 fragments become an .mp4
// (timestamps shifted to start at 0:00), MPEG-TS segments become a .ts.

export async function downloadFile(url: string, fileName: string): Promise<void> {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`Download failed: HTTP ${response.status}`)
  const type = response.headers.get('content-type') ?? ''
  if (type.includes('mpegurl') || new URL(url).pathname.endsWith('.m3u8')) {
    const clip = await stitchPlaylist(url, await response.text())
    save(clip, clip.type === 'video/mp2t' ? fileName.replace(/\.mp4$/, '.ts') : fileName)
    return
  }
  save(await response.blob(), fileName)
}

function save(blob: Blob, fileName: string) {
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = href
  link.download = fileName
  link.click()
  // Give the browser time to start the download before freeing the bytes.
  setTimeout(() => URL.revokeObjectURL(href), 60_000)
}

async function fetchBytes(url: string): Promise<Uint8Array> {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`Download failed: HTTP ${response.status}`)
  return new Uint8Array(await response.arrayBuffer())
}

async function fetchText(url: string): Promise<string> {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`Download failed: HTTP ${response.status}`)
  return response.text()
}

async function stitchPlaylist(playlistUrl: string, text: string): Promise<Blob> {
  let mediaUrl = playlistUrl
  let media = text
  // A master playlist: take its highest-bandwidth variant.
  if (text.includes('#EXT-X-STREAM-INF')) {
    const lines = text.split('\n').map((line) => line.trim())
    let best = { bandwidth: -1, uri: '' }
    lines.forEach((line, i) => {
      const bandwidth = Number(line.match(/^#EXT-X-STREAM-INF:.*?\bBANDWIDTH=(\d+)/)?.[1] ?? NaN)
      if (bandwidth > best.bandwidth && lines[i + 1]) best = { bandwidth, uri: lines[i + 1] }
    })
    mediaUrl = new URL(best.uri, playlistUrl).href
    media = await fetchText(mediaUrl)
  }

  const init = media.match(/#EXT-X-MAP:URI="([^"]+)"/)?.[1]
  const segments = media
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#'))
  const urls = [...(init ? [init] : []), ...segments].map((uri) => new URL(uri, mediaUrl).href)
  const parts = await Promise.all(urls.map(fetchBytes))

  const bytes = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0))
  let offset = 0
  for (const part of parts) {
    bytes.set(part, offset)
    offset += part.length
  }

  if (!init) return new Blob([bytes], { type: 'video/mp2t' })
  rebaseFragmentTimes(bytes)
  return new Blob([bytes], { type: 'video/mp4' })
}

// Live-stream fragments carry decode times counted from when the stream began
// (here, 1970), which players read as a decades-long timeline. Shift every
// moof > traf > tfdt so each track starts at 0.
function rebaseFragmentTimes(bytes: Uint8Array) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  const firstTime = new Map<number, bigint>()
  const boxType = (at: number) => String.fromCharCode(bytes[at + 4], bytes[at + 5], bytes[at + 6], bytes[at + 7])

  function walk(start: number, end: number, trackId: number) {
    let pos = start
    while (pos + 8 <= end) {
      let size = view.getUint32(pos)
      let header = 8
      if (size === 1) {
        size = Number(view.getBigUint64(pos + 8))
        header = 16
      } else if (size === 0) {
        size = end - pos
      }
      if (size < header) return
      const type = boxType(pos)
      const body = pos + header
      if (type === 'moof') {
        walk(body, pos + size, trackId)
      } else if (type === 'traf') {
        // tfhd comes first in a traf: version/flags (4 bytes), then track_ID.
        const tfhd = findChild(body, pos + size, 'tfhd')
        walk(body, pos + size, tfhd === null ? trackId : view.getUint32(tfhd + 12))
      } else if (type === 'tfdt') {
        const version = bytes[body]
        const at = body + 4
        const time = version === 1 ? view.getBigUint64(at) : BigInt(view.getUint32(at))
        const first = firstTime.get(trackId) ?? time
        firstTime.set(trackId, first)
        if (version === 1) view.setBigUint64(at, time - first)
        else view.setUint32(at, Number(time - first))
      }
      pos += size
    }
  }

  function findChild(start: number, end: number, type: string): number | null {
    let pos = start
    while (pos + 8 <= end) {
      const size = view.getUint32(pos)
      if (size < 8) return null
      if (boxType(pos) === type) return pos
      pos += size
    }
    return null
  }

  walk(0, bytes.length, 0)
}

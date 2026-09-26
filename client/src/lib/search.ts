import { cameraNumber } from './cameras'
import type { Camera } from './cameras'

// Forgiving camera search: typos, spelled-out words ("Northwest 13th Street"),
// area names, and extra words that match nothing are all fine. Typos only count
// when the word does not exist as typed, so "northbound" never finds "southbound".
// Numbers must match exactly or as a prefix, so "13" never finds "18".

const SYNONYMS: Record<string, string> = {
  northwest: 'nw',
  southwest: 'sw',
  northeast: 'ne',
  southeast: 'se',
  street: 'st',
  str: 'st',
  road: 'rd',
  avenue: 'ave',
  av: 'ave',
  camera: 'cam',
  cameras: 'cam',
  cams: 'cam',
  nb: 'northbound',
  sb: 'southbound',
  first: '1',
  second: '2',
  third: '3',
  fourth: '4',
  fifth: '5',
  sixth: '6',
  seventh: '7',
  eighth: '8',
  ninth: '9',
  tenth: '10',
  thirteenth: '13',
  twentieth: '20',
}

// Filler, plus place names every camera shares.
const STOP_WORDS = new Set(['at', 'the', 'of', 'on', 'near', 'by', 'and', 'in', 'to', 'miami', 'dade', 'county', 'florida', 'fl'])

function tokenize(text: string): string[] {
  const words = text
    .toLowerCase()
    .replace(/#(\d+)/g, 'cam $1')
    // sw8th -> sw 8th, cam3 -> cam 3, i95 -> i 95 (rejoined just below).
    .replace(/([a-z])(\d)/g, '$1 $2')
    .replace(/\b(interstate|i)[\s-]*95\b/g, 'i95')
    .split(/[^a-z0-9]+/)
  const tokens: string[] = []
  for (const word of words) {
    if (!word) continue
    const cam = word.match(/^cams?(\d+)$/)
    if (cam) {
      tokens.push('cam', cam[1])
      continue
    }
    // 13th, 1st, and half-typed 13t all become 13.
    const ordinal = word.match(/^(\d+)(s|st|n|nd|r|rd|t|th)$/)
    const token = ordinal ? ordinal[1] : (SYNONYMS[word] ?? word)
    if (!STOP_WORDS.has(token)) tokens.push(token)
  }
  return tokens
}

// Edit distance counting a swapped pair of letters as one edit ("downtwon").
function editDistance(a: string, b: string) {
  const d = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array<number>(b.length).fill(0)])
  for (let j = 1; j <= b.length; j++) d[0][j] = j
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) d[i][j] = Math.min(d[i][j], d[i - 2][j - 2] + 1)
    }
  }
  return d[a.length][b.length]
}

// 3 exact, 2 prefix (still typing), 0 otherwise.
function exactScore(part: string, words: string[]) {
  return Math.max(0, ...words.map((word) => (word === part ? 3 : word.startsWith(part) ? 2 : 0)))
}

// How far the typed word is from a camera's closest word, or from the start of it.
function typoDistance(part: string, words: string[]) {
  return Math.min(...words.map((word) => Math.min(editDistance(part, word), editDistance(part, word.slice(0, part.length)))))
}

// One typed word scored against every camera. Typos (score 1) only count when no
// camera has the word as typed, and only for the closest spelling.
function scorePart(part: string, cameraWords: string[][]) {
  const exact = cameraWords.map((words) => exactScore(part, words))
  if (exact.some((score) => score > 0) || /\d/.test(part) || part.length < 4) return exact
  const distances = cameraWords.map((words) => typoDistance(part, words))
  const best = Math.min(...distances)
  const allowed = part.length >= 7 ? 2 : 1
  return distances.map((d) => (d === best && d <= allowed ? 1 : 0))
}

// Matching cameras, best first. An empty query returns every camera in order.
export function searchCameras(cameras: Camera[], query: string): Camera[] {
  const parts = tokenize(query)
  if (!parts.length) return cameras

  // "cam 3" or "#3" means that camera exactly.
  if (parts.length === 2 && parts[0] === 'cam' && /^\d+$/.test(parts[1])) {
    return cameras.filter((c) => cameraNumber(c.id) === Number(parts[1]))
  }

  const cameraWords = cameras.map((camera) =>
    tokenize(`cam ${cameraNumber(camera.id)} ${camera.name} ${camera.direction} ${camera.keywords.join(' ')}`),
  )
  // Ignore typed words that match no camera at all.
  const columns = parts.map((part) => scorePart(part, cameraWords)).filter((col) => col.some((score) => score > 0))
  if (!columns.length) return []

  const scored = cameras.map((camera, i) => ({
    camera,
    matched: columns.filter((col) => col[i] > 0).length,
    score: columns.reduce((sum, col) => sum + col[i], 0),
  }))
  // Cameras matching the most words; when none match them all, that shows the closest ones.
  const most = Math.max(...scored.map((s) => s.matched))
  return scored
    .filter((s) => s.matched === most)
    .sort((a, b) => b.score - a.score)
    .map((s) => s.camera)
}

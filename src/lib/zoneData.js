const RECENT_STORAGE_KEY = 'route-difficulty-recent-postcodes-v1'
const MAX_RECENT = 10

export class ZoneNotFoundError extends Error {
  constructor(postcode) {
    super(`Zone not found: ${postcode}`)
    this.name = 'ZoneNotFoundError'
  }
}

export function normalizePostcode(value) {
  return String(value ?? '').replace(/\D/g, '').slice(0, 5)
}

export function assetUrl(path) {
  const base = import.meta.env?.BASE_URL || '/'
  return `${base.endsWith('/') ? base : `${base}/`}${String(path).replace(/^\//, '')}`
}

export async function loadManifest(fetchImpl = fetch) {
  const response = await fetchImpl(assetUrl('data/manifest.json'), { cache: 'no-store' })
  if (!response.ok) throw new Error(`Manifest request failed: ${response.status}`)
  const manifest = await response.json()
  if (!manifest?.datasetVersion || !Number.isInteger(Number(manifest.zoneCount))) throw new Error('Invalid data manifest')
  return manifest
}

export function zoneDataPath(postcode, manifest) {
  const normalized = normalizePostcode(postcode)
  if (!/^\d{5}$/.test(normalized)) throw new TypeError('postcode must be a 5-digit string')
  const version = String(manifest?.datasetVersion || '').trim()
  if (!/^[A-Za-z0-9._-]+$/.test(version)) throw new TypeError('invalid dataset version')
  return `data/releases/${version}/zones/${normalized.slice(0, 2)}/${normalized}.json`
}

export async function loadZone(postcode, manifest, fetchImpl = fetch) {
  const normalized = normalizePostcode(postcode)
  const response = await fetchImpl(assetUrl(zoneDataPath(normalized, manifest)), { cache: 'force-cache' })
  if (response.status === 404) throw new ZoneNotFoundError(normalized)
  if (!response.ok) throw new Error(`Zone request failed: ${response.status}`)
  const zone = await response.json()
  if (zone?.postcode !== normalized || !zone?.geometry?.type) throw new Error('Invalid zone payload')
  return zone
}

function safeStorage(storage) {
  if (storage) return storage
  if (typeof localStorage !== 'undefined') return localStorage
  return null
}

export function loadRecentSearches(storage) {
  try {
    const parsed = JSON.parse(safeStorage(storage)?.getItem(RECENT_STORAGE_KEY) || '[]')
    if (!Array.isArray(parsed)) return []
    return parsed.filter((item) => /^\d{5}$/.test(String(item?.postcode || ''))).slice(0, MAX_RECENT)
  } catch {
    return []
  }
}

export function addRecentSearch(entry, storage) {
  const target = safeStorage(storage)
  const postcode = normalizePostcode(entry?.postcode)
  if (!/^\d{5}$/.test(postcode)) return loadRecentSearches(target)
  const next = [
    { postcode, label: String(entry?.label || '').trim(), searchedAt: new Date().toISOString() },
    ...loadRecentSearches(target).filter((item) => item.postcode !== postcode),
  ].slice(0, MAX_RECENT)
  try { target?.setItem(RECENT_STORAGE_KEY, JSON.stringify(next)) } catch { /* storage can be disabled */ }
  return next
}

export function geometryPolygons(geometry) {
  if (geometry?.type === 'Polygon') return [geometry.coordinates]
  if (geometry?.type === 'MultiPolygon') return geometry.coordinates
  return []
}

export function geometryBounds(geometry) {
  const points = geometryPolygons(geometry).flat(2)
  if (!points.length) return null
  return points.reduce((bounds, point) => ({
    minLng: Math.min(bounds.minLng, Number(point[0])),
    maxLng: Math.max(bounds.maxLng, Number(point[0])),
    minLat: Math.min(bounds.minLat, Number(point[1])),
    maxLat: Math.max(bounds.maxLat, Number(point[1])),
  }), { minLng: Infinity, maxLng: -Infinity, minLat: Infinity, maxLat: -Infinity })
}

export function formatNumber(value, maximumFractionDigits = 1) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return String(value ?? '')
  return new Intl.NumberFormat('ko-KR', { maximumFractionDigits }).format(numeric)
}

export function formatDate(value) {
  if (!value) return '확인 불가'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: 'short', day: 'numeric' }).format(date)
}

export const recentStorageKey = RECENT_STORAGE_KEY

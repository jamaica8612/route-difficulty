import assert from 'node:assert/strict'
import test from 'node:test'
import {
  addRecentSearch,
  geometryBounds,
  geometryPolygons,
  loadRecentSearches,
  loadZone,
  normalizePostcode,
  recentStorageKey,
  zoneDataPath,
  ZoneNotFoundError,
} from '../src/lib/zoneData.js'

class MemoryStorage {
  constructor() { this.values = new Map() }
  getItem(key) { return this.values.get(key) ?? null }
  setItem(key, value) { this.values.set(key, value) }
}

test('postcode input keeps only five digits', () => {
  assert.equal(normalizePostcode(' 47-502abc9'), '47502')
})

test('zone data is sharded by the first two postcode digits', () => {
  assert.equal(
    zoneDataPath('47502', { datasetVersion: '2026-08' }),
    'data/releases/2026-08/zones/47/47502.json',
  )
  assert.throws(() => zoneDataPath('1234', { datasetVersion: '2026-08' }), TypeError)
  assert.throws(() => zoneDataPath('47502', { datasetVersion: '../secret' }), TypeError)
})

test('recent history is deduplicated and capped at ten entries', () => {
  const storage = new MemoryStorage()
  for (let index = 0; index < 12; index += 1) {
    addRecentSearch({ postcode: String(10000 + index), label: `구역 ${index}` }, storage)
  }
  addRecentSearch({ postcode: '10005', label: '다시 조회' }, storage)
  const recent = loadRecentSearches(storage)
  assert.equal(recent.length, 10)
  assert.equal(recent[0].postcode, '10005')
  assert.equal(recent[0].label, '다시 조회')
  assert.equal(JSON.parse(storage.getItem(recentStorageKey)).length, 10)
})

test('polygon and multipolygon bounds retain all coordinate parts', () => {
  const polygon = { type: 'Polygon', coordinates: [[[127, 35], [128, 35], [128, 36], [127, 35]]] }
  const multi = { type: 'MultiPolygon', coordinates: [polygon.coordinates, [[[129, 34], [130, 34], [130, 35], [129, 34]]]] }
  assert.equal(geometryPolygons(polygon).length, 1)
  assert.equal(geometryPolygons(multi).length, 2)
  assert.deepEqual(geometryBounds(multi), { minLng: 127, maxLng: 130, minLat: 34, maxLat: 36 })
})

test('missing zone is reported separately from network errors', async () => {
  const fetchImpl = async () => ({ ok: false, status: 404 })
  await assert.rejects(
    () => loadZone('47502', { datasetVersion: '2026-08' }, fetchImpl),
    ZoneNotFoundError,
  )
})

test('zone payload must match the requested postcode and contain geometry', async () => {
  const fetchImpl = async () => ({
    ok: true,
    status: 200,
    json: async () => ({ postcode: '47503', geometry: { type: 'Polygon', coordinates: [] } }),
  })
  await assert.rejects(() => loadZone('47502', { datasetVersion: '2026-08' }, fetchImpl), /Invalid zone payload/)
})

import { useEffect, useMemo, useRef, useState } from 'react'
import { Map, MapPin } from 'lucide-react'
import { geometryBounds, geometryPolygons } from '../lib/zoneData.js'

let naverMapsPromise

function loadNaverMaps(clientId) {
  if (!clientId) return Promise.resolve(false)
  if (window.naver?.maps) return Promise.resolve(true)
  if (naverMapsPromise) return naverMapsPromise
  naverMapsPromise = new Promise((resolve, reject) => {
    const existing = document.getElementById('naver-maps-sdk')
    if (existing) {
      existing.addEventListener('load', () => resolve(Boolean(window.naver?.maps)), { once: true })
      existing.addEventListener('error', reject, { once: true })
      return
    }
    const script = document.createElement('script')
    script.id = 'naver-maps-sdk'
    script.async = true
    script.src = `https://oapi.map.naver.com/openapi/v3/maps.js?ncpKeyId=${encodeURIComponent(clientId)}`
    script.onload = () => resolve(Boolean(window.naver?.maps))
    script.onerror = () => reject(new Error('Naver Maps SDK failed to load'))
    document.head.appendChild(script)
  })
  return naverMapsPromise
}

export default function ZoneMap({ geometry, postcode }) {
  const mapElement = useRef(null)
  const [mapReady, setMapReady] = useState(false)
  const [mapFailed, setMapFailed] = useState(false)
  const clientId = import.meta.env.VITE_NAVER_MAP_CLIENT_ID || ''

  useEffect(() => {
    let cancelled = false
    let overlays = []
    let map
    if (!clientId || !geometry || !mapElement.current) return undefined
    loadNaverMaps(clientId)
      .then((loaded) => {
        if (!loaded || cancelled || !mapElement.current) return
        const naver = window.naver
        const bounds = geometryBounds(geometry)
        if (!bounds) return
        map = new naver.maps.Map(mapElement.current, {
          center: new naver.maps.LatLng((bounds.minLat + bounds.maxLat) / 2, (bounds.minLng + bounds.maxLng) / 2),
          zoom: 15,
          scaleControl: false,
          mapDataControl: false,
          zoomControl: true,
          zoomControlOptions: { position: naver.maps.Position.TOP_RIGHT },
        })
        const latLngBounds = new naver.maps.LatLngBounds()
        overlays = geometryPolygons(geometry).map((polygon) => {
          const paths = polygon.map((ring) => ring.map(([lng, lat]) => {
            const point = new naver.maps.LatLng(lat, lng)
            latLngBounds.extend(point)
            return point
          }))
          return new naver.maps.Polygon({
            map,
            paths,
            fillColor: '#165b3f',
            fillOpacity: 0.22,
            strokeColor: '#164b37',
            strokeOpacity: 0.95,
            strokeWeight: 3,
          })
        })
        map.fitBounds(latLngBounds, { top: 48, right: 36, bottom: 48, left: 36 })
        setMapReady(true)
      })
      .catch(() => { if (!cancelled) setMapFailed(true) })
    return () => {
      cancelled = true
      overlays.forEach((overlay) => overlay.setMap(null))
      overlays = []
      map = null
    }
  }, [clientId, geometry])

  return (
    <section className="zone-map" aria-label={`우편번호 ${postcode} 구역 지도`}>
      <div ref={mapElement} className={`naver-map ${mapReady ? 'ready' : ''}`} />
      {(!clientId || mapFailed) && <BoundaryPreview geometry={geometry} />}
      {!mapReady && !mapFailed && clientId && <div className="map-loading"><Map className="spin" /><span>네이버 지도를 불러오는 중</span></div>}
      <div className="map-label"><MapPin size={14} /><strong>{postcode}</strong><span>우편구역 경계</span></div>
      {!clientId && <span className="map-key-notice">네이버 지도 키 설정 전 · 경계 미리보기</span>}
      {mapFailed && <span className="map-key-notice error">네이버 지도 연결 실패 · 경계 미리보기</span>}
    </section>
  )
}

function BoundaryPreview({ geometry }) {
  const bounds = geometryBounds(geometry)
  const paths = useMemo(() => {
    if (!bounds) return []
    const width = Math.max(bounds.maxLng - bounds.minLng, 0.000001)
    const height = Math.max(bounds.maxLat - bounds.minLat, 0.000001)
    const scale = Math.min(86 / width, 72 / height)
    const drawWidth = width * scale
    const drawHeight = height * scale
    const offsetX = (100 - drawWidth) / 2
    const offsetY = (100 - drawHeight) / 2
    return geometryPolygons(geometry).flatMap((polygon) => polygon.map((ring) => ring.map(([lng, lat], index) => {
      const x = offsetX + (lng - bounds.minLng) * scale
      const y = offsetY + (bounds.maxLat - lat) * scale
      return `${index ? 'L' : 'M'}${x.toFixed(2)},${y.toFixed(2)}`
    }).join(' ') + ' Z'))
  }, [bounds, geometry])
  return (
    <div className="boundary-preview" aria-hidden="true">
      <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
        <defs><pattern id="map-grid" width="10" height="10" patternUnits="userSpaceOnUse"><path d="M10 0H0V10" fill="none" stroke="#dfe7de" strokeWidth=".5" /></pattern></defs>
        <rect width="100" height="100" fill="url(#map-grid)" />
        {paths.map((path, index) => <path key={`${path.slice(0, 24)}-${index}`} d={path} fill="#2f7455" fillOpacity=".22" stroke="#18513a" strokeWidth="1.1" vectorEffect="non-scaling-stroke" />)}
      </svg>
    </div>
  )
}

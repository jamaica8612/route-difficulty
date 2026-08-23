import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  ArrowDownUp,
  Building2,
  CalendarClock,
  CarFront,
  CheckCircle2,
  Clock3,
  Database,
  Home,
  Info,
  Layers3,
  MapPin,
  RefreshCw,
  Search,
  ShieldCheck,
} from 'lucide-react'
import ZoneMap from './components/ZoneMap.jsx'
import {
  addRecentSearch,
  formatDate,
  formatNumber,
  loadManifest,
  loadRecentSearches,
  loadZone,
  normalizePostcode,
  ZoneNotFoundError,
} from './lib/zoneData.js'

const TAG_STYLES = {
  NO_ELEVATOR_4F_PLUS: 'danger',
  LOW_PARKING_RATIO: 'warning',
  LARGE_COMPLEX: 'info',
}

function nullable(value, suffix = '') {
  if (value === null || value === undefined || value === '') return '확인 불가'
  return `${formatNumber(value)}${suffix}`
}

function percent(value) {
  if (value === null || value === undefined) return '확인 불가'
  return `${Math.round(Number(value))}%`
}

function postcodeLabel(zone) {
  const parts = [zone?.region?.sido, zone?.region?.sigungu, zone?.region?.eupmyeondong].filter(Boolean)
  return parts.length ? parts.join(' ') : `우편번호 ${zone?.postcode || ''}`
}

export default function App() {
  const [manifest, setManifest] = useState(null)
  const [manifestError, setManifestError] = useState('')
  const [postcode, setPostcode] = useState('')
  const [zone, setZone] = useState(null)
  const [recent, setRecent] = useState(loadRecentSearches)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    loadManifest()
      .then((data) => {
        if (!cancelled) setManifest(data)
      })
      .catch(() => {
        if (!cancelled) setManifestError('공식 데이터 목록을 불러오지 못했습니다. 잠시 뒤 다시 시도해 주세요.')
      })
    return () => { cancelled = true }
  }, [])

  const datasetStatus = useMemo(() => {
    if (manifestError) return { tone: 'error', label: '자료 연결 오류' }
    if (!manifest) return { tone: 'loading', label: '자료 확인 중' }
    if (!manifest.zoneCount) return { tone: 'warning', label: '전국 자료 생성 중' }
    return { tone: 'ready', label: `${formatNumber(manifest.zoneCount)}개 구역 준비됨` }
  }, [manifest, manifestError])

  async function searchZone(value = postcode) {
    const normalized = normalizePostcode(value)
    setPostcode(normalized)
    setError('')
    if (!/^\d{5}$/.test(normalized)) {
      setZone(null)
      setError('우편번호 숫자 5자리를 입력해 주세요.')
      return
    }
    if (!manifest) {
      setError(manifestError || '자료 목록을 확인하고 있습니다. 잠시 뒤 다시 눌러 주세요.')
      return
    }

    setLoading(true)
    try {
      const result = await loadZone(normalized, manifest)
      setZone(result)
      const next = addRecentSearch({ postcode: normalized, label: postcodeLabel(result) })
      setRecent(next)
    } catch (searchError) {
      setZone(null)
      if (searchError instanceof ZoneNotFoundError) {
        setError(manifest.zoneCount
          ? '이 우편번호의 공식 자료를 찾지 못했습니다. 번호를 확인하거나 다음 자료 갱신을 기다려 주세요.'
          : '전국 공식 자료를 생성하고 있습니다. 데이터 준비가 끝나면 이 번호를 조회할 수 있습니다.')
      } else {
        setError('구역 자료를 불러오지 못했습니다. 인터넷 연결을 확인하고 다시 시도해 주세요.')
      }
    } finally {
      setLoading(false)
    }
  }

  function onSubmit(event) {
    event.preventDefault()
    searchZone()
  }

  const summary = zone?.summary || {}
  const coverage = zone?.coverage || {}
  const attentionBuildings = zone?.attentionBuildings || []

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="구역판독 홈">
          <span className="brand-mark"><MapPin size={20} strokeWidth={2.7} /></span>
          <span><strong>구역판독</strong><small>택배 구역 공식정보</small></span>
        </a>
        <div className={`dataset-badge ${datasetStatus.tone}`}>
          <span aria-hidden="true" />{datasetStatus.label}
        </div>
      </header>

      <main>
        <section className="search-hero">
          <div className="hero-copy">
            <span className="eyebrow"><ShieldCheck size={15} /> 로그인·고객정보 없이</span>
            <h1>계약 전에<br /><em>우편번호부터</em> 확인하세요.</h1>
            <p>층수, 승강기, 세대수, 주차대수처럼 공식 자료로 확인되는 사실만 모았습니다. 실제 계단과 진입 동선은 현장에서 다시 확인해야 합니다.</p>
          </div>

          <div className="search-panel">
            <form onSubmit={onSubmit} noValidate>
              <label htmlFor="postcode">확인할 우편번호</label>
              <div className={`postcode-input ${error ? 'has-error' : ''}`}>
                <Search size={22} />
                <input
                  id="postcode"
                  value={postcode}
                  onChange={(event) => setPostcode(normalizePostcode(event.target.value))}
                  inputMode="numeric"
                  autoComplete="postal-code"
                  maxLength={5}
                  placeholder="예: 47502"
                  aria-describedby={error ? 'search-error' : undefined}
                />
                <button type="submit" disabled={loading || !manifest}>
                  {loading ? <RefreshCw className="spin" size={18} /> : '구역 확인'}
                </button>
              </div>
            </form>

            {error && <p className="search-error" id="search-error"><AlertTriangle size={15} />{error}</p>}
            {!error && manifest?.generatedAt && (
              <p className="dataset-date"><CalendarClock size={14} /> 자료 생성일 {formatDate(manifest.generatedAt)}</p>
            )}

            <div className="recent-searches">
              <span><Clock3 size={14} /> 최근 검색</span>
              {recent.length ? (
                <div>{recent.map((item) => (
                  <button key={item.postcode} type="button" onClick={() => searchZone(item.postcode)}>
                    <strong>{item.postcode}</strong><small>{item.label}</small>
                  </button>
                ))}</div>
              ) : <p>조회에 성공한 우편번호가 이 기기에만 저장됩니다.</p>}
            </div>
          </div>
        </section>

        {!zone && <EmptyGuide manifest={manifest} />}

        {zone && (
          <div className="result-layout">
            <section className="result-main">
              <div className="result-heading">
                <div>
                  <span className="eyebrow">POSTCODE {zone.postcode}</span>
                  <h2>{postcodeLabel(zone)}</h2>
                  <p>공식 자료에 기록된 건물 구조를 우편구역 경계 안에서 합산했습니다.</p>
                </div>
                <span className="no-score"><CheckCircle2 size={15} /> 종합점수 없음</span>
              </div>

              <ZoneMap geometry={zone.geometry} postcode={zone.postcode} />

              <section className="summary-section" aria-labelledby="summary-title">
                <div className="section-title">
                  <div><span className="eyebrow">ZONE FACTS</span><h3 id="summary-title">구역 기본정보</h3></div>
                  <span>{nullable(zone.areaM2 ? zone.areaM2 / 1_000_000 : null, '㎢')}</span>
                </div>
                <div className="summary-grid">
                  <SummaryCard icon={<Building2 />} label="주소 연결 건물" value={nullable(summary.buildings?.total, '동')} note={`주거용 ${nullable(summary.buildings?.residential, '동')}`} />
                  <SummaryCard icon={<Home />} label="기록 세대" value={nullable(summary.households?.total, '세대')} note="공식 대장 합계" />
                  <SummaryCard icon={<ArrowDownUp />} label="승강기 0대" value={nullable(summary.elevators?.zeroBuildings, '동')} note={`확인 ${nullable(summary.elevators?.knownBuildings, '동')}`} />
                  <SummaryCard icon={<CarFront />} label="등록 주차" value={nullable(summary.parking?.totalSpaces, '대')} note={`세대당 ${nullable(summary.parking?.spacesPerHousehold, '대')}`} />
                </div>
              </section>

              <HousingMix housingTypes={summary.housingTypes} />

              <section className="attention-section" aria-labelledby="attention-title">
                <div className="section-title">
                  <div><span className="eyebrow">CHECK FIRST</span><h3 id="attention-title">먼저 확인할 건물</h3></div>
                  <span>최대 30개</span>
                </div>
                <p className="section-description">난이도 판정이 아니라 아래 공개 조건에 해당하는 건물을 추린 목록입니다.</p>
                {attentionBuildings.length ? (
                  <div className="building-list">
                    {attentionBuildings.map((building) => <AttentionBuilding key={building.id} building={building} />)}
                  </div>
                ) : (
                  <div className="empty-box"><CheckCircle2 /><div><strong>표시 조건에 해당하는 건물이 없습니다.</strong><p>자료가 없다는 뜻은 아니므로 현장 확인은 필요합니다.</p></div></div>
                )}
                {zone.attentionOmittedCount > 0 && <p className="omitted-note">같은 조건의 건물 {formatNumber(zone.attentionOmittedCount)}개는 목록에서 생략했습니다.</p>}
              </section>
            </section>

            <aside className="result-aside">
              <CoverageCard coverage={coverage} />
              <SourceCard sources={zone.sources || []} generatedAt={zone.generatedAt || manifest?.generatedAt} />
              <div className="limits-card">
                <Info size={19} />
                <div><strong>이 자료로 알 수 없는 것</strong><p>실제 계단 상태, 불법주차, 차단기 대기, 막다른 길, 후진 출차 여부는 포함되지 않습니다.</p></div>
              </div>
            </aside>
          </div>
        )}
      </main>

      <footer>
        <strong>구역판독</strong>
        <p>공공데이터를 배송 계약 전 참고하기 쉽게 정리한 도구입니다. 현장 안전과 실제 작업 조건을 보장하지 않습니다.</p>
      </footer>
    </div>
  )
}

function EmptyGuide({ manifest }) {
  return (
    <section className="guide-section">
      <article><span><Database /></span><h2>공식 자료만</h2><p>건축물대장과 K-apt에 기록된 값만 표시하고 없는 값은 ‘확인 불가’로 남깁니다.</p></article>
      <article><span><Layers3 /></span><h2>구역 단위 요약</h2><p>우편번호 경계 안의 건물·세대·승강기·주차 현황을 한 화면에서 확인합니다.</p></article>
      <article><span><AlertTriangle /></span><h2>주의 조건 공개</h2><p>점수 대신 어떤 조건으로 건물이 추려졌는지 수치와 함께 그대로 보여줍니다.</p></article>
      {manifest && !manifest.zoneCount && (
        <div className="build-notice"><RefreshCw /><div><strong>전국 데이터 첫 생성을 준비하고 있습니다.</strong><p>앱 구조는 준비됐으며 공식 원본 파일 수집이 완료되면 우편번호 검색이 열립니다.</p></div></div>
      )}
    </section>
  )
}

function SummaryCard({ icon, label, value, note }) {
  return <article className="summary-card"><span>{icon}</span><div><small>{label}</small><strong>{value}</strong><p>{note}</p></div></article>
}

function HousingMix({ housingTypes = {} }) {
  const values = [
    ['아파트', housingTypes.apartmentHouseholds],
    ['빌라·연립', housingTypes.villaHouseholds],
    ['오피스텔', housingTypes.officetelHouseholds],
    ['단독·다가구', housingTypes.detachedHouseholds],
  ]
  const total = values.reduce((sum, [, value]) => sum + (Number(value) || 0), 0)
  if (!total) return null
  return (
    <section className="housing-section">
      <div className="section-title"><div><span className="eyebrow">HOUSING MIX</span><h3>주택 유형</h3></div><span>세대수 기준</span></div>
      <div className="mix-bar" aria-label="주택 유형 비율">
        {values.map(([label, value], index) => Number(value) > 0 && <span key={label} className={`mix-${index}`} style={{ width: `${Number(value) / total * 100}%` }} title={`${label} ${formatNumber(value)}세대`} />)}
      </div>
      <div className="mix-legend">{values.map(([label, value], index) => <div key={label}><i className={`mix-${index}`} /><span>{label}</span><strong>{nullable(value, '세대')}</strong></div>)}</div>
    </section>
  )
}

function AttentionBuilding({ building }) {
  return (
    <article className="building-card">
      <div className="building-heading">
        <span className="building-icon"><Building2 /></span>
        <div><h4>{building.name || '건물명 없음'}</h4><p><MapPin size={13} />{building.address || '주소 확인 불가'}</p></div>
        <small>{building.source === 'K_APT' ? 'K-apt' : '건축물대장'}</small>
      </div>
      <div className="building-facts">
        <span>지상층 <strong>{nullable(building.groundFloors)}</strong></span>
        <span>승객용 승강기 <strong>{nullable(building.elevators, '대')}</strong></span>
        <span>세대 <strong>{nullable(building.households, '세대')}</strong></span>
        <span>주차 <strong>{nullable(building.parkingSpaces, '대')}</strong></span>
      </div>
      <div className="tag-list">{(building.tags || []).map((tag) => (
        <span key={tag.code || tag.label} className={TAG_STYLES[tag.code] || 'info'}>
          {tag.label}<small>{tag.evidence}</small>
        </span>
      ))}</div>
    </article>
  )
}

function CoverageCard({ coverage }) {
  const matched = coverage.addressMatchedCount === null || coverage.addressMatchedCount === undefined ? null : Number(coverage.addressMatchedCount)
  const unmatched = coverage.unmatchedCount === null || coverage.unmatchedCount === undefined ? null : Number(coverage.unmatchedCount)
  const total = matched !== null && unmatched !== null ? matched + unmatched : null
  const matchPercent = total ? Math.round(matched / total * 100) : null
  const rows = [
    ['주소 연결', matchPercent],
    ['층수 확인', coverage.floorsKnownPercent],
    ['승강기 확인', coverage.elevatorsKnownPercent],
    ['주차 확인', coverage.parkingKnownPercent],
  ]
  return (
    <section className="aside-card coverage-card">
      <span className="eyebrow">DATA COVERAGE</span><h3>자료 확인률</h3>
      <p>확인률이 낮은 구역은 합계도 실제보다 작을 수 있습니다.</p>
      <div>{rows.map(([label, value]) => (
        <div className="coverage-row" key={label}>
          <span>{label}<strong>{percent(value)}</strong></span>
          <i><b style={{ width: `${Math.max(0, Math.min(100, Number(value) || 0))}%` }} /></i>
        </div>
      ))}</div>
      <dl><div><dt>연결 성공</dt><dd>{nullable(matched, '건')}</dd></div><div><dt>연결 실패</dt><dd>{nullable(unmatched, '건')}</dd></div></dl>
    </section>
  )
}

function SourceCard({ sources, generatedAt }) {
  return (
    <section className="aside-card source-card">
      <span className="eyebrow">SOURCE</span><h3>자료 출처</h3>
      <ul>{sources.map((source) => (
        <li key={`${source.name}-${source.referenceDate || ''}`}>
          {source.url ? <a href={source.url} target="_blank" rel="noreferrer">{source.name}</a> : <strong>{source.name}</strong>}
          <span>{source.referenceDate ? `기준 ${formatDate(source.referenceDate)}` : '기준일 확인 불가'}</span>
        </li>
      ))}</ul>
      <p><CalendarClock size={14} /> 이 파일 생성일 {formatDate(generatedAt)}</p>
    </section>
  )
}

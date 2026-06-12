import 'leaflet/dist/leaflet.css'
import L from 'leaflet'
import { useEffect, useRef, useState } from 'react'
import tzlookup from 'tz-lookup'
import iconUrl from 'leaflet/dist/images/marker-icon.png'
import iconRetinaUrl from 'leaflet/dist/images/marker-icon-2x.png'
import shadowUrl from 'leaflet/dist/images/marker-shadow.png'
import { C, F, fieldStyle } from '../theme'

// Resolve a lat/lon to an IANA timezone in the browser — a pure JS lookup
// with no native dependencies, so it works reliably regardless of what's
// installed on the server (e.g. timezonefinder on a Raspberry Pi).
function resolveTimezone(lat: number, lng: number): string | undefined {
  try {
    return tzlookup(lat, lng)
  } catch {
    // Open ocean / poles — no timezone polygon at this point.
    return undefined
  }
}

// Fix Leaflet's broken default icon paths when bundled with Vite
const DEFAULT_ICON = L.icon({
  iconUrl,
  iconRetinaUrl,
  shadowUrl,
  iconSize:    [25, 41],
  iconAnchor:  [12, 41],
  popupAnchor: [1, -34],
  shadowSize:  [41, 41],
})

// ── Types ──────────────────────────────────────────────────────────────────────

export interface LocationValue {
  latitude: number
  longitude: number
  radius_km?: number
  name?: string
  timezone?: string
}

interface Suggestion {
  lat: string
  lon: string
  display_name: string
}

interface Props {
  title: string
  value: unknown
  showRadius?: boolean
  radiusMin?: number
  radiusMax?: number
  onChange: (v: LocationValue) => void
}

// ── Component ──────────────────────────────────────────────────────────────────

export default function LocationMapInput({
  title,
  value,
  showRadius = false,
  radiusMin = 1,
  radiusMax = 500,
  onChange,
}: Props) {
  const loc = (typeof value === 'object' && value !== null ? value : {}) as LocationValue
  const lat = loc.latitude ?? 0
  const lng = loc.longitude ?? 0
  const radius = loc.radius_km ?? 50
  const name = loc.name ?? ''

  const [search, setSearch] = useState(name)
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState('')
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [activeIdx, setActiveIdx] = useState(-1)

  const debounceRef  = useRef<ReturnType<typeof setTimeout> | null>(null)
  const wrapperRef   = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef       = useRef<L.Map | null>(null)
  const markerRef    = useRef<L.Marker | null>(null)
  const circleRef    = useRef<L.Circle | null>(null)

  // Always-current refs so map event handlers never capture stale values
  const onChangeRef = useRef(onChange)
  const locRef      = useRef({ lat, lng, radius, showRadius, name })
  useEffect(() => { onChangeRef.current = onChange })
  useEffect(() => { locRef.current = { lat, lng, radius, showRadius, name } })

  // ── Click outside to close dropdown ──────────────────────────────────────

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setShowSuggestions(false)
        setActiveIdx(-1)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // ── Build the value object to emit ────────────────────────────────────────

  const emit = (patch: Partial<{ latitude: number; longitude: number; radius_km: number; name: string }>) => {
    const { lat: curLat, lng: curLng, radius: curRadius, showRadius: curShow, name: curName } = locRef.current
    const newLat = 'latitude'  in patch ? patch.latitude!  : curLat
    const newLng = 'longitude' in patch ? patch.longitude! : curLng
    const next: LocationValue = { latitude: newLat, longitude: newLng }
    if (curShow) next.radius_km = 'radius_km' in patch ? patch.radius_km! : curRadius
    // Preserve the saved name unless the patch explicitly provides one (including '')
    const nextName = 'name' in patch ? patch.name! : curName
    if (nextName) next.name = nextName
    // Re-resolve whenever the pin moves so the stored timezone always
    // matches the current coordinates.
    const timezone = resolveTimezone(newLat, newLng)
    if (timezone) next.timezone = timezone
    onChangeRef.current(next)
  }

  // ── Map initialisation (once on mount) ────────────────────────────────────

  useEffect(() => {
    if (!containerRef.current) return

    const hasPin = lat !== 0 || lng !== 0
    const center: L.LatLngTuple = hasPin ? [lat, lng] : [37.7749, -122.4194]

    const map = L.map(containerRef.current, {
      center,
      zoom: hasPin ? 11 : 4,
    })

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19,
    }).addTo(map)

    // Click to place / move pin
    map.on('click', (e: L.LeafletMouseEvent) => {
      const { lat: newLat, lng: newLng } = e.latlng
      setSearch('')
      emit({ latitude: newLat, longitude: newLng, name: '' })
    })

    mapRef.current = map

    // Place initial marker + circle if we already have a location
    if (hasPin) {
      const m = L.marker([lat, lng], { icon: DEFAULT_ICON, draggable: true }).addTo(map)
      m.on('dragend', () => {
        const p = m.getLatLng()
        setSearch('')
        emit({ latitude: p.lat, longitude: p.lng, name: '' })
      })
      markerRef.current = m

      if (showRadius) {
        const circle = L.circle([lat, lng], {
          radius: radius * 1000,
          color: '#4a90d9', fillColor: '#4a90d9', fillOpacity: 0.2, weight: 2,
        }).addTo(map)
        circleRef.current = circle
        map.fitBounds(circle.getBounds(), { padding: [20, 20] })
      }
    }

    return () => {
      map.remove()
      mapRef.current = null
      markerRef.current = null
      circleRef.current = null
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Sync marker + circle when lat/lng changes ────────────────────────────

  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const hasPin = lat !== 0 || lng !== 0
    if (!hasPin) return

    // Update or create marker
    if (markerRef.current) {
      markerRef.current.setLatLng([lat, lng])
    } else {
      const m = L.marker([lat, lng], { icon: DEFAULT_ICON, draggable: true }).addTo(map)
      m.on('dragend', () => {
        const p = m.getLatLng()
        setSearch('')
        emit({ latitude: p.lat, longitude: p.lng, name: '' })
      })
      markerRef.current = m
    }

    // Update or create circle, then fit view to show it
    if (showRadius) {
      if (circleRef.current) {
        circleRef.current.setLatLng([lat, lng])
      } else {
        circleRef.current = L.circle([lat, lng], {
          radius: radius * 1000,
          color: '#4a90d9', fillColor: '#4a90d9', fillOpacity: 0.2, weight: 2,
        }).addTo(map)
      }
      map.fitBounds(circleRef.current.getBounds(), { padding: [20, 20] })
    } else if (circleRef.current) {
      circleRef.current.remove()
      circleRef.current = null
    }
  }, [lat, lng, showRadius])  // intentionally excludes `radius` — slider has its own effect

  // ── Sync circle radius when slider changes (without re-fitting the view) ──

  useEffect(() => {
    if (!circleRef.current) return
    circleRef.current.setRadius(radius * 1000)
  }, [radius])

  // ── Fly to a new location (search + lat/lon inputs) ──────────────────────
  // When showRadius=true, skip flyTo — fitBounds in the sync effect handles it.

  const flyTo = (newLat: number, newLng: number) => {
    if (showRadius) return
    mapRef.current?.flyTo([newLat, newLng], Math.max(mapRef.current.getZoom(), 11))
  }

  // ── Autocomplete ──────────────────────────────────────────────────────────

  const fetchSuggestions = async (q: string) => {
    if (q.trim().length < 2) {
      setSuggestions([])
      setShowSuggestions(false)
      return
    }
    try {
      const resp = await fetch(
        `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=json&limit=5`,
        { headers: { 'Accept-Language': 'en' } }
      )
      const results: Suggestion[] = await resp.json()
      setSuggestions(results)
      setShowSuggestions(results.length > 0)
      setActiveIdx(-1)
    } catch {
      setSuggestions([])
      setShowSuggestions(false)
    }
  }

  const handleSearchChange = (val: string) => {
    setSearch(val)
    setSearchError('')
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (val.trim().length >= 2) {
      debounceRef.current = setTimeout(() => fetchSuggestions(val), 300)
    } else {
      setSuggestions([])
      setShowSuggestions(false)
    }
  }

  const selectSuggestion = (s: Suggestion) => {
    const newLat = Number(s.lat)
    const newLng = Number(s.lon)
    flyTo(newLat, newLng)
    // Show first two comma-parts in the input so the field reflects the selection
    const parts = s.display_name.split(',')
    const short = parts.length > 1
      ? `${parts[0].trim()}, ${parts[1].trim()}`
      : parts[0].trim()
    setSearch(short)
    emit({ latitude: newLat, longitude: newLng, name: short })
    setSuggestions([])
    setShowSuggestions(false)
    setActiveIdx(-1)
    setSearchError('')
  }

  // ── Geocoding (GO button / Enter with no highlighted suggestion) ──────────

  const geocode = async () => {
    // Apply a keyboard-highlighted suggestion directly
    if (activeIdx >= 0 && suggestions[activeIdx]) {
      selectSuggestion(suggestions[activeIdx])
      return
    }
    // Apply the first visible suggestion if the list is open
    if (showSuggestions && suggestions.length > 0) {
      selectSuggestion(suggestions[0])
      return
    }
    // Fresh search fallback (e.g. user typed and pressed Enter without waiting)
    const q = search.trim()
    if (!q) return
    setSearching(true)
    setSearchError('')
    try {
      const resp = await fetch(
        `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=json&limit=1`,
        { headers: { 'Accept-Language': 'en' } }
      )
      const results: Array<{ lat: string; lon: string; display_name: string }> = await resp.json()
      if (!results.length) { setSearchError('Address not found'); return }
      selectSuggestion(results[0])
    } catch {
      setSearchError('Geocoding failed')
    } finally {
      setSearching(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!showSuggestions || !suggestions.length) {
      if (e.key === 'Enter') geocode()
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx(i => Math.min(i + 1, suggestions.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx(i => Math.max(i - 1, -1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      geocode()
    } else if (e.key === 'Escape') {
      setShowSuggestions(false)
      setActiveIdx(-1)
    }
  }

  // ── Styles ────────────────────────────────────────────────────────────────

  const inputSm: React.CSSProperties = { ...fieldStyle, fontSize: F.size.sm, padding: '5px 8px' }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <span style={{ color: C.textSecondary, fontFamily: F.family, fontSize: F.size.label }}>
        {title}
      </span>

      {/* Address search with autocomplete */}
      <div ref={wrapperRef} style={{ position: 'relative' }}>
        <div style={{ display: 'flex', gap: 6 }}>
          <input
            type="text"
            value={search}
            onChange={e => handleSearchChange(e.target.value)}
            onKeyDown={handleKeyDown}
            onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
            placeholder="Search city, address, or place…"
            style={{ ...inputSm, flex: 1 }}
            autoComplete="off"
          />
          <button
            type="button"
            onClick={geocode}
            disabled={searching}
            style={{
              background: C.surface, border: `1px solid ${C.border}`,
              color: searching ? C.textDim : C.textSecondary,
              padding: '5px 12px', cursor: searching ? 'default' : 'pointer',
              borderRadius: 3, fontFamily: F.family, fontSize: F.size.sm,
              letterSpacing: F.tracking.wide, flexShrink: 0,
            }}
          >
            {searching ? '…' : 'GO'}
          </button>
        </div>

        {/* Autocomplete dropdown */}
        {showSuggestions && suggestions.length > 0 && (
          <div style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            zIndex: 1000,
            background: C.surface,
            border: `1px solid ${C.border}`,
            borderTop: 'none',
            borderRadius: '0 0 4px 4px',
            boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
            overflow: 'hidden',
          }}>
            {suggestions.map((s, i) => {
              const parts = s.display_name.split(',')
              const primary   = parts[0].trim()
              const secondary = parts.slice(1).join(',').trim()
              const isActive  = i === activeIdx
              return (
                <button
                  key={i}
                  type="button"
                  onMouseDown={e => { e.preventDefault(); selectSuggestion(s) }}
                  onMouseEnter={() => setActiveIdx(i)}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 2,
                    width: '100%',
                    padding: '8px 10px',
                    background: isActive ? C.surfaceHover : 'transparent',
                    border: 'none',
                    borderBottom: i < suggestions.length - 1 ? `1px solid ${C.border}` : 'none',
                    cursor: 'pointer',
                    textAlign: 'left',
                  }}
                >
                  <span style={{ color: C.textPrimary, fontFamily: F.family, fontSize: F.size.sm }}>
                    {primary}
                  </span>
                  {secondary && (
                    <span style={{ color: C.textDim, fontFamily: F.family, fontSize: F.size.xs }}>
                      {secondary}
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        )}
      </div>

      {searchError && (
        <span style={{ color: C.negative, fontSize: F.size.xs, fontFamily: F.family }}>
          {searchError}
        </span>
      )}

      {/* Map container — Leaflet attaches here */}
      <div
        ref={containerRef}
        style={{ height: 220, borderRadius: 4, border: `1px solid ${C.border}`, zIndex: 0 }}
      />

      {/* Lat / lon fields */}
      <div style={{ display: 'flex', gap: 10 }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, fontSize: F.size.sm, color: C.textMuted, fontFamily: F.family }}>
          Latitude
          <input
            type="number" step="any" value={lat}
            onChange={e => {
              const v = Number(e.target.value)
              flyTo(v, lng)
              setSearch('')
              emit({ latitude: v, name: '' })
            }}
            style={inputSm}
          />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, fontSize: F.size.sm, color: C.textMuted, fontFamily: F.family }}>
          Longitude
          <input
            type="number" step="any" value={lng}
            onChange={e => {
              const v = Number(e.target.value)
              flyTo(lat, v)
              setSearch('')
              emit({ longitude: v, name: '' })
            }}
            style={inputSm}
          />
        </label>
      </div>

      {/* Radius slider */}
      {showRadius && (
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: F.size.sm, color: C.textMuted, fontFamily: F.family }}>
          <span>
            Radius:{' '}
            <span style={{ color: C.textSecondary }}>{radius} km</span>
          </span>
          <input
            type="range" min={radiusMin} max={radiusMax} value={radius}
            onChange={e => emit({ radius_km: Number(e.target.value) })}
            style={{ accentColor: C.sage }}
          />
        </label>
      )}
    </div>
  )
}

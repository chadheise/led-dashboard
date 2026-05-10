import 'leaflet/dist/leaflet.css'
import L from 'leaflet'
import { useEffect, useRef, useState } from 'react'
import iconUrl from 'leaflet/dist/images/marker-icon.png'
import iconRetinaUrl from 'leaflet/dist/images/marker-icon-2x.png'
import shadowUrl from 'leaflet/dist/images/marker-shadow.png'
import { C, F, fieldStyle } from '../theme'

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

  const [search, setSearch] = useState('')
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState('')

  // DOM container for the map
  const containerRef = useRef<HTMLDivElement>(null)

  // Leaflet instances — never trigger re-renders
  const mapRef    = useRef<L.Map | null>(null)
  const markerRef = useRef<L.Marker | null>(null)
  const circleRef = useRef<L.Circle | null>(null)

  // Always-current refs so map event handlers never capture stale values
  const onChangeRef = useRef(onChange)
  const locRef      = useRef({ lat, lng, radius, showRadius })
  useEffect(() => { onChangeRef.current = onChange })
  useEffect(() => { locRef.current = { lat, lng, radius, showRadius } })

  // ── Build the value object to emit ────────────────────────────────────────

  const emit = (patch: Partial<{ latitude: number; longitude: number; radius_km: number }>) => {
    const { lat: curLat, lng: curLng, radius: curRadius, showRadius: curShow } = locRef.current
    const next: LocationValue = {
      latitude:  'latitude'  in patch ? patch.latitude!  : curLat,
      longitude: 'longitude' in patch ? patch.longitude! : curLng,
    }
    if (curShow) next.radius_km = 'radius_km' in patch ? patch.radius_km! : curRadius
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
      emit({ latitude: newLat, longitude: newLng })
    })

    mapRef.current = map

    // Place initial marker + circle if we already have a location
    if (hasPin) {
      const m = L.marker([lat, lng], { icon: DEFAULT_ICON, draggable: true }).addTo(map)
      m.on('dragend', () => {
        const p = m.getLatLng()
        emit({ latitude: p.lat, longitude: p.lng })
      })
      markerRef.current = m

      if (showRadius) {
        const circle = L.circle([lat, lng], {
          radius: radius * 1000,
          color: C.sage, fillColor: C.sage, fillOpacity: 0.08, weight: 1.5,
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
        emit({ latitude: p.lat, longitude: p.lng })
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
          color: C.sage, fillColor: C.sage, fillOpacity: 0.08, weight: 1.5,
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

  // ── Geocoding ─────────────────────────────────────────────────────────────

  const geocode = async () => {
    const q = search.trim()
    if (!q) return
    setSearching(true)
    setSearchError('')
    try {
      const resp = await fetch(
        `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=json&limit=1`,
        { headers: { 'Accept-Language': 'en' } }
      )
      const results: Array<{ lat: string; lon: string }> = await resp.json()
      if (!results.length) { setSearchError('Address not found'); return }
      const newLat = Number(results[0].lat)
      const newLng = Number(results[0].lon)
      flyTo(newLat, newLng)
      emit({ latitude: newLat, longitude: newLng })
      setSearch('')
    } catch {
      setSearchError('Geocoding failed')
    } finally {
      setSearching(false)
    }
  }

  // ── Styles ────────────────────────────────────────────────────────────────

  const inputSm: React.CSSProperties = { ...fieldStyle, fontSize: F.size.sm, padding: '5px 8px' }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <span style={{ color: C.textSecondary, fontFamily: F.family, fontSize: F.size.label }}>
        {title}
      </span>

      {/* Address search */}
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          type="text"
          value={search}
          onChange={e => { setSearch(e.target.value); setSearchError('') }}
          onKeyDown={e => e.key === 'Enter' && geocode()}
          placeholder="Search address or place…"
          style={{ ...inputSm, flex: 1 }}
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
              emit({ latitude: v })
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
              emit({ longitude: v })
            }}
            style={inputSm}
          />
        </label>
      </div>

      {/* Radius slider */}
      {showRadius && (
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: F.size.sm, color: C.textMuted, fontFamily: F.family }}>
          <span>
            Search radius:{' '}
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

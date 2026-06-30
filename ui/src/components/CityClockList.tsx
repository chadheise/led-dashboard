import { useRef, useState } from 'react'
import tzlookup from 'tz-lookup'
import { C, F, fieldStyle, labelStyle } from '../theme'

interface CityClock {
  name?: string
  timezone?: string
  color?: string
}

interface Props {
  title: string
  description?: string
  value: unknown
  onChange: (v: CityClock[]) => void
  /** Local-time row: rendered first when shown, with its own color picker. */
  showLocal?: boolean
  localColor?: string
  onLocalColorChange?: (color: string) => void
}

interface CitySuggestion {
  name: string       // "City, Country" for display + storage
  timezone: string   // IANA zone resolved from the result's coordinates
}

interface NominatimResult {
  lat: string
  lon: string
  display_name: string
  address?: Record<string, string>
}

const DEFAULT_COLOR = '#C8C8C8'
const SEARCH_LIMIT = 6

const colorSwatchStyle: React.CSSProperties = {
  width: 34, height: 34, padding: 2, cursor: 'pointer', flexShrink: 0,
  border: `1px solid ${C.border}`, borderRadius: 3, background: 'none',
}

const safeColor = (c: string | undefined): string =>
  /^#[0-9a-fA-F]{6}$/.test(c ?? '') ? (c as string) : DEFAULT_COLOR

const rowStyle: React.CSSProperties = {
  display: 'flex',
  gap: 8,
  alignItems: 'center',
  padding: '8px 10px',
  background: C.surface,
  borderRadius: 6,
  border: `1px solid ${C.border}`,
}

const addBtnStyle: React.CSSProperties = {
  padding: '6px 12px',
  background: C.positive,
  color: '#000',
  border: 'none',
  borderRadius: 4,
  cursor: 'pointer',
  fontSize: F.size.sm,
  fontFamily: F.family,
  fontWeight: 600,
  alignSelf: 'flex-start',
}

const removeBtnStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: C.textDim,
  cursor: 'pointer',
  padding: '0 4px',
  lineHeight: 1,
  fontSize: '1.2rem',
  flexShrink: 0,
}

const menuStyle: React.CSSProperties = {
  position: 'absolute',
  top: '100%',
  left: 0,
  right: 0,
  zIndex: 20,
  marginTop: 2,
  maxHeight: 220,
  overflowY: 'auto',
  background: C.surface,
  border: `1px solid ${C.border}`,
  borderRadius: 4,
}

const optionStyle: React.CSSProperties = {
  padding: '6px 10px',
  cursor: 'pointer',
  fontFamily: F.family,
  fontSize: F.size.sm,
  color: C.textSecondary,
}

/** Resolve an IANA timezone for a coordinate in the browser (no server dep). */
function resolveTimezone(lat: number, lon: number): string {
  try {
    return tzlookup(lat, lon)
  } catch {
    return ''   // open ocean / poles — no timezone polygon
  }
}

/** Turn one Nominatim hit into a city suggestion, or null if it has no zone. */
function toSuggestion(r: NominatimResult): CitySuggestion | null {
  const a = r.address ?? {}
  const city =
    a.city || a.town || a.village || a.municipality || a.hamlet ||
    a.county || r.display_name.split(',')[0].trim()
  const country = a.country ?? ''
  const timezone = resolveTimezone(Number(r.lat), Number(r.lon))
  if (!city || !timezone) return null
  return { name: country ? `${city}, ${country}` : city, timezone }
}

/** A single city row: a typeahead over every world city plus its own color. */
function CityRow({
  clock,
  onChange,
  onRemove,
}: {
  clock: CityClock
  onChange: (patch: Partial<CityClock>) => void
  onRemove: () => void
}) {
  const [query, setQuery] = useState<string | null>(null)   // null => show selected name
  const [suggestions, setSuggestions] = useState<CitySuggestion[]>([])
  const [loading, setLoading] = useState(false)
  const debounceRef = useRef<number | undefined>(undefined)
  const blurRef = useRef<number | undefined>(undefined)
  const reqRef = useRef(0)

  const text = query ?? (clock.name ?? '')

  const search = async (q: string) => {
    const id = ++reqRef.current
    setLoading(true)
    try {
      const resp = await fetch(
        `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}` +
          `&format=json&addressdetails=1&limit=${SEARCH_LIMIT}`,
        { headers: { 'Accept-Language': 'en' } },
      )
      const results: NominatimResult[] = await resp.json()
      if (id !== reqRef.current) return   // a newer query superseded this one
      const seen = new Set<string>()
      const hits: CitySuggestion[] = []
      for (const r of results) {
        const s = toSuggestion(r)
        if (s && !seen.has(s.name)) { seen.add(s.name); hits.push(s) }
      }
      setSuggestions(hits)
    } catch {
      if (id === reqRef.current) setSuggestions([])
    } finally {
      if (id === reqRef.current) setLoading(false)
    }
  }

  const onType = (val: string) => {
    setQuery(val)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (val.trim().length < 2) { setSuggestions([]); return }
    debounceRef.current = window.setTimeout(() => search(val.trim()), 300)
  }

  const pick = (s: CitySuggestion) => {
    onChange({ name: s.name, timezone: s.timezone })
    setQuery(null)
    setSuggestions([])
  }

  const showMenu = query !== null && (loading || suggestions.length > 0)

  return (
    <div style={rowStyle}>
      <div style={{ position: 'relative', flex: 1 }}>
        <input
          type="text"
          value={text}
          placeholder="Search any city..."
          onChange={e => onType(e.target.value)}
          onFocus={() => setQuery('')}
          onBlur={() => {
            // Delay so an option's onMouseDown registers before we close.
            blurRef.current = window.setTimeout(() => { setQuery(null); setSuggestions([]) }, 150)
          }}
          style={fieldStyle}
        />
        {showMenu && (
          <div style={menuStyle}>
            {loading && suggestions.length === 0 && (
              <div style={{ ...optionStyle, color: C.textDim, cursor: 'default' }}>Searching…</div>
            )}
            {suggestions.map((s, i) => (
              <div
                key={`${s.name}-${i}`}
                style={optionStyle}
                onMouseEnter={e => (e.currentTarget.style.background = C.surfaceHover)}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                // onMouseDown fires before the input's onBlur, so the pick lands.
                onMouseDown={e => { e.preventDefault(); clearTimeout(blurRef.current); pick(s) }}
              >
                {s.name}
              </div>
            ))}
          </div>
        )}
      </div>

      <input
        type="color"
        value={safeColor(clock.color)}
        onChange={e => onChange({ color: e.target.value })}
        title="Text color"
        style={colorSwatchStyle}
      />

      <button type="button" onClick={onRemove} style={removeBtnStyle} title="Remove">×</button>
    </div>
  )
}

/** The auto-resolved local clock: a fixed label plus its own color picker. */
function LocalRow({ color, onColorChange }: { color: string; onColorChange: (c: string) => void }) {
  return (
    <div style={rowStyle}>
      <span style={{ flex: 1, color: C.textSecondary, fontFamily: F.family, fontSize: F.size.sm }}>
        Local time
      </span>
      <input
        type="color"
        value={safeColor(color)}
        onChange={e => onColorChange(e.target.value)}
        title="Text color"
        style={colorSwatchStyle}
      />
      {/* Spacer matching the city rows' remove button so swatches align. */}
      <span style={{ width: 18, flexShrink: 0 }} aria-hidden />
    </div>
  )
}

export default function CityClockList({
  title, description, value, onChange,
  showLocal, localColor, onLocalColorChange,
}: Props) {
  const clocks: CityClock[] = Array.isArray(value) ? (value as CityClock[]) : []

  const update = (idx: number, patch: Partial<CityClock>) =>
    onChange(clocks.map((c, i) => (i === idx ? { ...c, ...patch } : c)))

  const add = () => onChange([...clocks, { name: '', timezone: '', color: DEFAULT_COLOR }])

  const remove = (idx: number) => onChange(clocks.filter((_, i) => i !== idx))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <span style={{ ...labelStyle, display: 'block' }}>{title}</span>
      {description && (
        <span style={{ color: C.textDim, fontSize: F.size.xs, fontFamily: F.family }}>{description}</span>
      )}

      {showLocal && onLocalColorChange && (
        <LocalRow color={localColor ?? DEFAULT_COLOR} onColorChange={onLocalColorChange} />
      )}

      {clocks.map((clock, idx) => (
        <CityRow
          key={idx}
          clock={clock}
          onChange={patch => update(idx, patch)}
          onRemove={() => remove(idx)}
        />
      ))}

      <button type="button" onClick={add} style={addBtnStyle}>+ Add city</button>
    </div>
  )
}

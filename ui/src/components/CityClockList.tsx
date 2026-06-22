import { useMemo, useRef, useState } from 'react'
import { C, F, fieldStyle, labelStyle } from '../theme'

interface CityClock {
  timezone: string
  color?: string
}

interface Option {
  value: string   // IANA timezone
  label: string   // "City, Country" or derived city name
}

interface Props {
  title: string
  description?: string
  options: Option[]
  value: unknown
  onChange: (v: CityClock[]) => void
  /** Local-time row: rendered first when shown, with its own color picker. */
  showLocal?: boolean
  localColor?: string
  onLocalColorChange?: (color: string) => void
}

const DEFAULT_COLOR = '#C8C8C8'
const MAX_RESULTS = 8

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

/** A single city row: a typeahead over every world city plus its own color. */
function CityRow({
  clock,
  options,
  labelFor,
  onChange,
  onRemove,
}: {
  clock: CityClock
  options: Option[]
  labelFor: (tz: string) => string
  onChange: (patch: Partial<CityClock>) => void
  onRemove: () => void
}) {
  const [query, setQuery] = useState<string | null>(null)   // null => show selected label
  const [open, setOpen] = useState(false)
  const blurTimer = useRef<number | undefined>(undefined)

  const selectedLabel = clock.timezone ? labelFor(clock.timezone) : ''
  const text = query ?? selectedLabel

  const matches = useMemo(() => {
    const q = (query ?? '').trim().toLowerCase()
    if (!q) return options.slice(0, MAX_RESULTS)
    return options
      .filter(o => o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q))
      .slice(0, MAX_RESULTS)
  }, [query, options])

  const pick = (o: Option) => {
    onChange({ timezone: o.value })
    setQuery(null)
    setOpen(false)
  }

  return (
    <div style={rowStyle}>
      <div style={{ position: 'relative', flex: 1 }}>
        <input
          type="text"
          value={text}
          placeholder="Search any city..."
          onChange={e => { setQuery(e.target.value); setOpen(true) }}
          onFocus={() => { setQuery(''); setOpen(true) }}
          onBlur={() => {
            // Delay so an option's onMouseDown registers before we close.
            blurTimer.current = window.setTimeout(() => { setOpen(false); setQuery(null) }, 120)
          }}
          style={fieldStyle}
        />
        {open && matches.length > 0 && (
          <div style={menuStyle}>
            {matches.map(o => (
              <div
                key={o.value}
                style={optionStyle}
                onMouseEnter={e => (e.currentTarget.style.background = C.surfaceHover)}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                // onMouseDown fires before the input's onBlur, so the pick lands.
                onMouseDown={e => { e.preventDefault(); clearTimeout(blurTimer.current); pick(o) }}
              >
                {o.label}
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
  title, description, options, value, onChange,
  showLocal, localColor, onLocalColorChange,
}: Props) {
  const clocks: CityClock[] = Array.isArray(value) ? (value as CityClock[]) : []
  const labelFor = useMemo(() => {
    const map = new Map(options.map(o => [o.value, o.label]))
    return (tz: string) => map.get(tz) ?? tz
  }, [options])

  const update = (idx: number, patch: Partial<CityClock>) =>
    onChange(clocks.map((c, i) => (i === idx ? { ...c, ...patch } : c)))

  const add = () => onChange([...clocks, { timezone: '', color: DEFAULT_COLOR }])

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
          options={options}
          labelFor={labelFor}
          onChange={patch => update(idx, patch)}
          onRemove={() => remove(idx)}
        />
      ))}

      <button type="button" onClick={add} style={addBtnStyle}>+ Add city</button>
    </div>
  )
}

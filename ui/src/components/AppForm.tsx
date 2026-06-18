import { C, F, fieldStyle, labelStyle } from '../theme'
import LocationMapInput from './LocationMapInput'
import DurationInput from './DurationInput'
import MultiPicker from './MultiPicker'
import TeamPicker from './TeamPicker'
import StreamList from './StreamList'
import FlightList from './FlightList'

// ── Schema types ───────────────────────────────────────────────────────────────

interface SchemaProperty {
  type: string
  title?: string
  default?: unknown
  enum?: string[]
  minimum?: number
  maximum?: number
  /** For arrays: item type + optional enum for multi-select */
  items?: { type: string; enum?: string[] }
  /** For compound object types (e.g. location) */
  properties?: Record<string, { type: string; default?: unknown; minimum?: number; maximum?: number }>
  /**
   * Custom input type — overrides default rendering.
   *
   * Built-in values:
   *   'text'         Plain text input (default for type:string)
   *   'integer'      Integer number input
   *   'float'        Decimal number input
   *   'boolean'      Checkbox toggle (default for type:boolean)
   *   'color'        Native color picker + hex field
   *   'datetime'     Native date+time picker; value is an ISO-ish "YYYY-MM-DDTHH:MM"
   *                  string, directly `datetime.fromisoformat`-parseable
   *   'date'         Native date-only picker; value is a "YYYY-MM-DD" string
   *   'location'     Paired latitude / longitude fields (value: {latitude,longitude})
   *   'flight-list'  List of {number,label} rows for the Flight Tracker app
   *   'multi-select' Checkbox group built from items.enum
   *   'multi-picker' Dropdown + pills selector for string arrays (uses x-enum-labels)
   *   'duration'     Number + unit selector ({value, unit}); units from x-duration-units
   *   'team-picker'  Dynamic league + team selector (string[] of "league:abbr")
   */
  'x-input-type'?: string
  /** Labels for multi-select options — map from option value to display label */
  'x-enum-labels'?: Record<string, string>
  /** Allowed time units for duration inputs */
  'x-duration-units'?: string[]
  /** Restrict the radius slider on location inputs (km). Takes precedence over radius_km.minimum/maximum. */
  'x-radius-min'?: number
  'x-radius-max'?: number
  /** Conditionally show this field only when another field equals a specific value. */
  'x-show-if'?: { field: string; equals: unknown }
  /** Hide this field entirely outside of Vite dev mode (npm run dev). */
  'x-dev-only'?: boolean
}

interface Schema {
  type: 'object'
  title?: string
  properties: Record<string, SchemaProperty>
  required?: string[]
}

interface Props {
  schema: Schema
  value: Record<string, unknown>
  onChange: (v: Record<string, unknown>) => void
}

// ── Shared sub-styles ──────────────────────────────────────────────────────────

const checkRow: React.CSSProperties = {
  ...labelStyle, flexDirection: 'row', alignItems: 'center', gap: 8,
}
const selectStyle: React.CSSProperties = { ...fieldStyle, appearance: 'none' }
const row2: React.CSSProperties = { display: 'flex', gap: 10 }

// ── Specialised input renderers ────────────────────────────────────────────────

function ColorInput({ title, value, onChange }: { title: string; value: unknown; onChange: (v: string) => void }) {
  const hex = String(value || '#000000')
  const safeHex = /^#[0-9a-fA-F]{6}$/.test(hex) ? hex : '#000000'
  return (
    <label style={labelStyle}>
      {title}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input
          type="color"
          value={safeHex}
          onChange={e => onChange(e.target.value)}
          style={{
            width: 36, height: 34, padding: 2, cursor: 'pointer',
            border: `1px solid ${C.border}`, borderRadius: 3, background: 'none',
          }}
        />
        <input
          type="text"
          value={hex}
          onChange={e => onChange(e.target.value)}
          placeholder="#FFFFFF"
          style={{ ...fieldStyle, flex: 1 }}
        />
      </div>
    </label>
  )
}

function DateTimeInput({ title, value, onChange }: { title: string; value: unknown; onChange: (v: string) => void }) {
  return (
    <label style={labelStyle}>
      {title}
      <input
        type="datetime-local"
        value={typeof value === 'string' ? value : ''}
        onChange={e => onChange(e.target.value)}
        style={fieldStyle}
      />
    </label>
  )
}

function DateInput({ title, value, onChange }: { title: string; value: unknown; onChange: (v: string) => void }) {
  return (
    <label style={labelStyle}>
      {title}
      <input
        type="date"
        value={typeof value === 'string' ? value : ''}
        onChange={e => onChange(e.target.value)}
        style={fieldStyle}
      />
    </label>
  )
}

function LocationInput({ title, value, onChange }: { title: string; value: unknown; onChange: (v: unknown) => void }) {
  const loc = (typeof value === 'object' && value !== null ? value : {}) as { latitude?: number; longitude?: number; name?: string }
  const set = (field: 'latitude' | 'longitude', n: number) => onChange({ ...loc, [field]: n, name: '' })
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={{ ...labelStyle, display: 'block' }}>{title}</span>
      <div style={row2}>
        <label style={{ ...labelStyle, flex: 1 }}>
          Latitude
          <input
            type="number" step="any"
            value={loc.latitude ?? 0}
            onChange={e => set('latitude', Number(e.target.value))}
            style={fieldStyle}
          />
        </label>
        <label style={{ ...labelStyle, flex: 1 }}>
          Longitude
          <input
            type="number" step="any"
            value={loc.longitude ?? 0}
            onChange={e => set('longitude', Number(e.target.value))}
            style={fieldStyle}
          />
        </label>
      </div>
    </div>
  )
}

function MultiSelectInput({ title, options, labels, value, onChange }: {
  title: string
  options: string[]
  labels?: Record<string, string>
  value: unknown
  onChange: (v: string[]) => void
}) {
  const selected = Array.isArray(value) ? (value as string[]) : []
  const toggle = (opt: string, checked: boolean) =>
    onChange(checked ? [...selected, opt] : selected.filter(x => x !== opt))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <span style={{ ...labelStyle, display: 'block' }}>{title}</span>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        {options.map(opt => (
          <label
            key={opt}
            style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: F.size.sm, color: C.textSecondary, cursor: 'pointer', fontFamily: F.family }}
          >
            <input
              type="checkbox"
              checked={selected.includes(opt)}
              onChange={e => toggle(opt, e.target.checked)}
              style={{ accentColor: C.positive }}
            />
            {labels?.[opt] ?? opt.toUpperCase()}
          </label>
        ))}
      </div>
    </div>
  )
}

// ── Main form ──────────────────────────────────────────────────────────────────

export default function AppForm({ schema, value, onChange }: Props) {
  const props = schema.properties ?? {}

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {Object.entries(props).map(([key, prop]) => {
        if (prop['x-dev-only'] && !import.meta.env.DEV) return null
        const showIf = prop['x-show-if']
        if (showIf) {
          const depVal = showIf.field in value ? value[showIf.field] : (props[showIf.field]?.default ?? false)
          if (depVal !== showIf.equals) return null
        }
        const v = key in value ? value[key] : (prop.default ?? '')
        const title = prop.title ?? key
        const xType = prop['x-input-type']

        // ── Custom input types (x-input-type overrides schema type) ─────────

        if (xType === 'color') {
          return (
            <ColorInput
              key={key}
              title={title}
              value={v}
              onChange={hex => onChange({ ...value, [key]: hex })}
            />
          )
        }

        if (xType === 'datetime') {
          return (
            <DateTimeInput
              key={key}
              title={title}
              value={v}
              onChange={dt => onChange({ ...value, [key]: dt })}
            />
          )
        }

        if (xType === 'date') {
          return (
            <DateInput
              key={key}
              title={title}
              value={v}
              onChange={d => onChange({ ...value, [key]: d })}
            />
          )
        }

        if (xType === 'flight-list') {
          // Migrate legacy {flight_numbers[], label} configs for display so an
          // instance saved before per-flight labels still shows its flights.
          let flightsVal = v
          if ((!Array.isArray(v) || v.length === 0) && Array.isArray(value.flight_numbers)) {
            const legacyLabel = typeof value.label === 'string' ? value.label : ''
            flightsVal = (value.flight_numbers as string[]).map((n, i) => ({
              number: n,
              label: i === 0 ? legacyLabel : '',
            }))
          }
          return (
            <FlightList
              key={key}
              title={title}
              value={flightsVal}
              onChange={flights => onChange({ ...value, [key]: flights })}
            />
          )
        }

        if (xType === 'location') {
          const radiusProp = prop.properties?.['radius_km']
          const showRadius = !!radiusProp
          const radiusMin = prop['x-radius-min'] ?? radiusProp?.minimum ?? 1
          const radiusMax = prop['x-radius-max'] ?? radiusProp?.maximum ?? 500
          return (
            <LocationMapInput
              key={key}
              title={title}
              value={v}
              showRadius={showRadius}
              radiusMin={radiusMin}
              radiusMax={radiusMax}
              onChange={loc => onChange({ ...value, [key]: loc })}
            />
          )
        }

        if (xType === 'multi-picker') {
          const options = (prop.items?.enum ?? []).map(v => ({
            value: v,
            label: prop['x-enum-labels']?.[v] ?? v,
          }))
          return (
            <MultiPicker
              key={key}
              title={title}
              options={options}
              value={v}
              onChange={sel => onChange({ ...value, [key]: sel })}
            />
          )
        }

        if (xType === 'multi-select') {
          const options = prop.items?.enum ?? []
          const labels = prop['x-enum-labels']
          return (
            <MultiSelectInput
              key={key}
              title={title}
              options={options}
              labels={labels}
              value={v}
              onChange={sel => onChange({ ...value, [key]: sel })}
            />
          )
        }

        if (xType === 'duration') {
          const allowedUnits = prop['x-duration-units'] ?? ['seconds', 'minutes', 'hours', 'days', 'months', 'years']
          return (
            <DurationInput
              key={key}
              title={title}
              value={v}
              allowedUnits={allowedUnits}
              onChange={dur => onChange({ ...value, [key]: dur })}
            />
          )
        }

        if (xType === 'team-picker') {
          return (
            <TeamPicker
              key={key}
              title={title}
              value={v}
              onChange={teams => onChange({ ...value, [key]: teams })}
            />
          )
        }

        if (xType === 'stream-list') {
          // Source options come from items.properties.source.enum
          const sourceOptions: string[] =
            (prop as { items?: { properties?: { source?: { enum?: string[] } } } })
              .items?.properties?.source?.enum ?? []
          return (
            <StreamList
              key={key}
              title={title}
              sourceOptions={sourceOptions}
              value={v}
              onChange={streams => onChange({ ...value, [key]: streams })}
            />
          )
        }

        // ── Default type-based rendering ────────────────────────────────────

        if (prop.type === 'boolean' || xType === 'boolean') {
          return (
            <label key={key} style={checkRow}>
              <input
                type="checkbox"
                checked={!!v}
                onChange={e => onChange({ ...value, [key]: e.target.checked })}
                style={{ accentColor: C.positive }}
              />
              <span style={{ color: C.textSecondary, fontFamily: F.family, fontSize: F.size.label }}>
                {title}
              </span>
            </label>
          )
        }

        if (prop.enum) {
          const enumLabels = prop['x-enum-labels']
          return (
            <label key={key} style={labelStyle}>
              {title}
              <select
                value={String(v)}
                onChange={e => onChange({ ...value, [key]: e.target.value })}
                style={selectStyle}
              >
                {prop.enum.map(opt => (
                  <option key={opt} value={opt}>{enumLabels?.[opt] ?? opt}</option>
                ))}
              </select>
            </label>
          )
        }

        if (prop.type === 'array') {
          return (
            <label key={key} style={labelStyle}>
              {title}
              <span style={{ color: C.textDim, fontSize: F.size.xs }}>(comma-separated)</span>
              <input
                type="text"
                value={Array.isArray(v) ? v.join(', ') : ''}
                onChange={e =>
                  onChange({ ...value, [key]: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })
                }
                style={fieldStyle}
              />
            </label>
          )
        }

        const isFloat  = prop.type === 'number'  || xType === 'float'
        const isInt    = prop.type === 'integer'  || xType === 'integer'
        const isNumeric = isFloat || isInt
        return (
          <label key={key} style={labelStyle}>
            {title}
            <input
              type={isNumeric ? 'number' : 'text'}
              value={String(v)}
              min={prop.minimum}
              max={prop.maximum}
              step={isInt ? 1 : isFloat ? 'any' : undefined}
              onChange={e =>
                onChange({ ...value, [key]: isNumeric ? Number(e.target.value) : e.target.value })
              }
              style={fieldStyle}
            />
          </label>
        )
      })}
    </div>
  )
}

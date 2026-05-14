import { C, F, fieldStyle, labelStyle } from '../theme'

// Stored as Record<string, number> e.g. {"days": 1, "hours": 5}
type DurationValue = Record<string, number>

interface Props {
  title: string
  value: unknown
  allowedUnits: string[]
  onChange: (v: DurationValue) => void
}

const ALL_UNITS = ['seconds', 'minutes', 'hours', 'days', 'months', 'years']

const UNIT_MAX: Record<string, number> = {
  seconds: 59,
  minutes: 59,
  hours: 23,
  // days, months, years: no upper cap
}

function capitalize(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

function parseValue(value: unknown, units: string[]): DurationValue {
  if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
    const obj = value as Record<string, unknown>
    // New multi-period format: {"days": 1, "hours": 5}
    if (units.some(u => u in obj) && !('unit' in obj)) {
      const result: DurationValue = {}
      for (const u of units) result[u] = typeof obj[u] === 'number' ? (obj[u] as number) : 0
      return result
    }
    // Old single-period format: {"value": N, "unit": "hours"} — migrate
    if ('value' in obj && 'unit' in obj) {
      const unit = String(obj.unit)
      const result: DurationValue = {}
      for (const u of units) result[u] = 0
      if (units.includes(unit)) result[unit] = Number(obj.value) || 0
      return result
    }
  }
  // Fallback: zeroes
  const result: DurationValue = {}
  for (const u of units) result[u] = 0
  return result
}

export default function DurationInput({ title, value, allowedUnits, onChange }: Props) {
  const units = allowedUnits.length > 0 ? allowedUnits : ALL_UNITS
  const parsed = parseValue(value, units)

  const update = (unit: string, n: number) => {
    const max = UNIT_MAX[unit]
    const clamped = max !== undefined ? Math.min(max, Math.max(0, Math.floor(n))) : Math.max(0, Math.floor(n))
    onChange({ ...parsed, [unit]: clamped })
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={{ ...labelStyle, display: 'block' }}>{title}</span>
      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        {units.map(unit => (
          <label
            key={unit}
            style={{
              display: 'flex', flexDirection: 'column', gap: 3,
              fontFamily: F.family, fontSize: F.size.xs, color: C.textMuted,
              letterSpacing: '0.05em',
            }}
          >
            {capitalize(unit)}
            <input
              type="number"
              min={0}
              max={UNIT_MAX[unit]}
              step={1}
              value={parsed[unit] ?? 0}
              onChange={e => update(unit, Number(e.target.value))}
              style={{ ...fieldStyle, width: 60, textAlign: 'center' }}
            />
          </label>
        ))}
      </div>
    </div>
  )
}

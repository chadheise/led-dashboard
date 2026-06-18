import { C, F, fieldStyle, labelStyle } from '../theme'

interface Flight {
  number: string
  label?: string
}

interface Props {
  title: string
  value: unknown
  onChange: (v: Flight[]) => void
}

const MAX_FLIGHTS = 5

const rowStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 6,
  padding: '10px 12px',
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
  padding: '4px 8px',
  background: C.negative,
  color: '#fff',
  border: 'none',
  borderRadius: 4,
  cursor: 'pointer',
  fontSize: F.size.xs,
  fontFamily: F.family,
  alignSelf: 'flex-end',
}

const DEFAULT_FLIGHT: Flight = { number: '', label: '' }

export default function FlightList({ title, value, onChange }: Props) {
  const flights: Flight[] = Array.isArray(value) && (value as Flight[]).length > 0
    ? (value as Flight[])
    : [{ ...DEFAULT_FLIGHT }]

  const update = (idx: number, patch: Partial<Flight>) => {
    onChange(flights.map((f, i) => (i === idx ? { ...f, ...patch } : f)))
  }

  const add = () => {
    if (flights.length >= MAX_FLIGHTS) return
    onChange([...flights, { ...DEFAULT_FLIGHT }])
  }

  const remove = (idx: number) => {
    if (flights.length <= 1) return
    onChange(flights.filter((_, i) => i !== idx))
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <span style={{ ...labelStyle, display: 'block' }}>{title}</span>

      {flights.map((flight, idx) => (
        <div key={idx} style={rowStyle}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ color: C.textSecondary, fontFamily: F.family, fontSize: F.size.sm }}>
              Flight {idx + 1}
            </span>
            {flights.length > 1 && (
              <button onClick={() => remove(idx)} style={removeBtnStyle}>Remove</button>
            )}
          </div>

          <label style={labelStyle}>
            Flight number
            <input
              type="text"
              value={flight.number ?? ''}
              onChange={e => update(idx, { number: e.target.value })}
              placeholder="DL1070"
              style={fieldStyle}
            />
          </label>

          <label style={labelStyle}>
            Label{' '}
            <span style={{ color: C.textDim, fontSize: F.size.xs }}>(optional)</span>
            <input
              type="text"
              value={flight.label ?? ''}
              onChange={e => update(idx, { label: e.target.value })}
              placeholder="Mom's flight"
              style={fieldStyle}
            />
          </label>
        </div>
      ))}

      {flights.length < MAX_FLIGHTS && (
        <button onClick={add} style={addBtnStyle}>+ Add flight</button>
      )}
    </div>
  )
}

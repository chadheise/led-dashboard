import { C, F, fieldStyle, labelStyle } from '../theme'

interface Stream {
  source: string
  symbols?: string[]
}

interface Props {
  title: string
  sourceOptions: string[]
  value: unknown
  onChange: (v: Stream[]) => void
}

const SOURCE_LABELS: Record<string, string> = {
  custom: 'Custom',
  tech: 'Tech',
  largest_market_cap: 'Largest Market Cap (dynamic)',
  finance: 'Finance',
  healthcare: 'Healthcare',
  energy: 'Energy',
  sp500: 'S&P 500 (index + all components)',
  nasdaq: 'NASDAQ-100 (index + components)',
  dow: 'Dow Jones 30 (index + components)',
}

const rowStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 6,
  padding: '10px 12px',
  background: C.surface,
  borderRadius: 6,
  border: `1px solid ${C.border}`,
}

const selectStyle: React.CSSProperties = {
  ...fieldStyle,
  appearance: 'none' as const,
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

const DEFAULT_STREAM: Stream = { source: 'custom', symbols: ['AAPL', 'MSFT', 'GOOGL', 'META', 'AMZN', 'TSLA', 'NVDA'] }

export default function StreamList({ title, sourceOptions, value, onChange }: Props) {
  const streams: Stream[] = Array.isArray(value) && (value as Stream[]).length > 0
    ? (value as Stream[])
    : [{ ...DEFAULT_STREAM }]

  const update = (idx: number, patch: Partial<Stream>) => {
    const next = streams.map((s, i) => i === idx ? { ...s, ...patch } : s)
    onChange(next)
  }

  const add = () => onChange([...streams, { ...DEFAULT_STREAM }])

  const remove = (idx: number) => {
    if (streams.length <= 1) return
    onChange(streams.filter((_, i) => i !== idx))
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <span style={{ ...labelStyle, display: 'block' }}>{title}</span>

      {streams.map((stream, idx) => (
        <div key={idx} style={rowStyle}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ color: C.textSecondary, fontFamily: F.family, fontSize: F.size.sm }}>
              Row {idx + 1}
            </span>
            {streams.length > 1 && (
              <button onClick={() => remove(idx)} style={removeBtnStyle}>Remove</button>
            )}
          </div>

          <label style={labelStyle}>
            Source
            <select
              value={stream.source}
              onChange={e => update(idx, { source: e.target.value })}
              style={selectStyle}
            >
              {sourceOptions.map(opt => (
                <option key={opt} value={opt}>{SOURCE_LABELS[opt] ?? opt}</option>
              ))}
            </select>
          </label>

          {stream.source === 'custom' && (
            <label style={labelStyle}>
              Symbols{' '}
              <span style={{ color: C.textDim, fontSize: F.size.xs }}>(comma-separated)</span>
              <input
                type="text"
                value={Array.isArray(stream.symbols) ? stream.symbols.join(', ') : ''}
                onChange={e =>
                  update(idx, {
                    symbols: e.target.value.split(',').map(s => s.trim().toUpperCase()).filter(Boolean),
                  })
                }
                placeholder="AAPL, MSFT, GOOGL"
                style={fieldStyle}
              />
            </label>
          )}
        </div>
      ))}

      <button onClick={add} style={addBtnStyle}>+ Add row</button>
    </div>
  )
}

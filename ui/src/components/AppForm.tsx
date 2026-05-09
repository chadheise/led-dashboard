import { C, F, fieldStyle, labelStyle } from '../theme'

interface SchemaProperty {
  type: string
  title?: string
  default?: unknown
  enum?: string[]
  minimum?: number
  maximum?: number
  items?: { type: string }
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

const checkRow: React.CSSProperties = {
  ...labelStyle,
  flexDirection: 'row',
  alignItems: 'center',
  gap: 8,
}

const selectStyle: React.CSSProperties = {
  ...fieldStyle,
  appearance: 'none',
}

export default function AppForm({ schema, value, onChange }: Props) {
  const props = schema.properties ?? {}

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {Object.entries(props).map(([key, prop]) => {
        const v = key in value ? value[key] : (prop.default ?? '')

        if (prop.type === 'boolean') {
          return (
            <label key={key} style={checkRow}>
              <input
                type="checkbox"
                checked={!!v}
                onChange={e => onChange({ ...value, [key]: e.target.checked })}
                style={{ accentColor: C.positive }}
              />
              <span style={{ color: C.textSecondary, fontFamily: F.family, fontSize: F.size.label }}>
                {prop.title ?? key}
              </span>
            </label>
          )
        }

        if (prop.enum) {
          return (
            <label key={key} style={labelStyle}>
              {prop.title ?? key}
              <select
                value={String(v)}
                onChange={e => onChange({ ...value, [key]: e.target.value })}
                style={selectStyle}
              >
                {prop.enum.map(opt => <option key={opt} value={opt}>{opt}</option>)}
              </select>
            </label>
          )
        }

        if (prop.type === 'array') {
          return (
            <label key={key} style={labelStyle}>
              {prop.title ?? key}
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

        const isNumeric = prop.type === 'number' || prop.type === 'integer'
        return (
          <label key={key} style={labelStyle}>
            {prop.title ?? key}
            <input
              type={isNumeric ? 'number' : 'text'}
              value={String(v)}
              min={prop.minimum}
              max={prop.maximum}
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

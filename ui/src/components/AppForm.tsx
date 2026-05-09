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

const label: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
  fontSize: '0.75rem',
  color: '#888',
}

const input: React.CSSProperties = {
  background: '#1a1a1a',
  border: '1px solid #333',
  color: '#ccc',
  padding: '6px 8px',
  borderRadius: 3,
  fontSize: '0.8rem',
  fontFamily: 'monospace',
}

export default function AppForm({ schema, value, onChange }: Props) {
  const props = schema.properties ?? {}

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {Object.entries(props).map(([key, prop]) => {
        const v = key in value ? value[key] : (prop.default ?? '')

        if (prop.type === 'boolean') {
          return (
            <label key={key} style={{ ...label, flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <input
                type="checkbox"
                checked={!!v}
                onChange={e => onChange({ ...value, [key]: e.target.checked })}
              />
              {prop.title ?? key}
            </label>
          )
        }

        if (prop.enum) {
          return (
            <label key={key} style={label}>
              {prop.title ?? key}
              <select
                value={String(v)}
                onChange={e => onChange({ ...value, [key]: e.target.value })}
                style={input}
              >
                {prop.enum.map(opt => <option key={opt} value={opt}>{opt}</option>)}
              </select>
            </label>
          )
        }

        if (prop.type === 'array') {
          return (
            <label key={key} style={label}>
              {prop.title ?? key} <span style={{ color: '#444' }}>(comma-separated)</span>
              <input
                type="text"
                value={Array.isArray(v) ? v.join(', ') : ''}
                onChange={e =>
                  onChange({ ...value, [key]: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })
                }
                style={input}
              />
            </label>
          )
        }

        const isNumeric = prop.type === 'number' || prop.type === 'integer'
        return (
          <label key={key} style={label}>
            {prop.title ?? key}
            <input
              type={isNumeric ? 'number' : 'text'}
              value={String(v)}
              min={prop.minimum}
              max={prop.maximum}
              onChange={e =>
                onChange({ ...value, [key]: isNumeric ? Number(e.target.value) : e.target.value })
              }
              style={input}
            />
          </label>
        )
      })}
    </div>
  )
}

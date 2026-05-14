import { useState, useEffect } from 'react'
import { C, F, fieldStyle, labelStyle } from '../theme'

interface Option {
  value: string
  label: string
}

interface Props {
  title: string
  options: Option[]
  value: unknown
  onChange: (v: string[]) => void
}

export default function MultiPicker({ title, options, value, onChange }: Props) {
  const selected = Array.isArray(value) ? (value as string[]) : []
  const available = options.filter(o => !selected.includes(o.value))

  const [pending, setPending] = useState(available[0]?.value ?? '')

  // Keep pending valid when selected list changes
  useEffect(() => {
    if (!available.find(o => o.value === pending)) {
      setPending(available[0]?.value ?? '')
    }
  }, [selected.join(',')])

  const add = () => {
    if (!pending) return
    onChange([...selected, pending])
  }

  const remove = (v: string) => onChange(selected.filter(x => x !== v))

  const selectStyle: React.CSSProperties = { ...fieldStyle, flex: 1, appearance: 'none' as const }
  const addBtnStyle: React.CSSProperties = {
    background: 'none',
    border: `1px solid ${C.border}`,
    color: C.textSecondary,
    padding: '6px 12px',
    cursor: 'pointer',
    borderRadius: 3,
    fontFamily: F.family,
    fontSize: F.size.sm,
    letterSpacing: '0.05em',
    flexShrink: 0,
    whiteSpace: 'nowrap' as const,
  }
  const pillStyle: React.CSSProperties = {
    background: C.surface,
    border: `1px solid ${C.border}`,
    color: C.textSecondary,
    borderRadius: 3,
    padding: '3px 8px',
    fontSize: F.size.sm,
    fontFamily: F.family,
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  }
  const removeBtnStyle: React.CSSProperties = {
    background: 'none',
    border: 'none',
    color: C.textDim,
    cursor: 'pointer',
    padding: 0,
    lineHeight: 1,
    fontSize: '1.1rem',
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <span style={{ ...labelStyle, display: 'block' }}>{title}</span>

      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <select
          value={pending}
          onChange={e => setPending(e.target.value)}
          style={selectStyle}
          disabled={available.length === 0}
        >
          {available.length === 0
            ? <option>All added</option>
            : available.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))
          }
        </select>
        <button
          type="button"
          onClick={add}
          disabled={available.length === 0}
          style={{ ...addBtnStyle, opacity: available.length === 0 ? 0.4 : 1 }}
        >
          + ADD
        </button>
      </div>

      {selected.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {selected.map(v => {
            const opt = options.find(o => o.value === v)
            return (
              <span key={v} style={pillStyle}>
                {opt?.label ?? v}
                <button type="button" onClick={() => remove(v)} style={removeBtnStyle}>
                  ×
                </button>
              </span>
            )
          })}
        </div>
      )}
    </div>
  )
}

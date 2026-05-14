import { useState, useEffect } from 'react'
import { C, F, fieldStyle, labelStyle } from '../theme'

interface League {
  id: string
  label: string
  filter?: string   // present on score-filter variants (e.g. ncaaf-top25)
  groups?: string   // present on conference variants (e.g. ncaaf-acc)
}

interface Team {
  id: string
  abbreviation: string
  display_name: string
  conference?: string
}

interface Props {
  title: string
  value: unknown
  onChange: (v: string[]) => void
}

const LAST_GROUPS = ['Independent', 'Division II', 'Division III', 'Other']

function groupByConference(teams: Team[]): [string, Team[]][] {
  const grouped: Record<string, Team[]> = {}
  for (const t of teams) {
    const key = t.conference || 'Independent'
    if (!grouped[key]) grouped[key] = []
    grouped[key].push(t)
  }
  // Sort: named conferences alphabetically, then Independent/D-II/D-III/Other at the end
  return Object.entries(grouped).sort(([a], [b]) => {
    const aLast = LAST_GROUPS.indexOf(a)
    const bLast = LAST_GROUPS.indexOf(b)
    if (aLast !== -1 && bLast !== -1) return aLast - bLast
    if (aLast !== -1) return 1
    if (bLast !== -1) return -1
    return a.localeCompare(b)
  })
}

export default function TeamPicker({ title, value, onChange }: Props) {
  const selected = Array.isArray(value) ? (value as string[]) : []

  const [leagues, setLeagues] = useState<League[]>([])
  const [league, setLeague] = useState('')
  const [teams, setTeams] = useState<Team[]>([])
  const [teamAbbr, setTeamAbbr] = useState('')
  const [loadingTeams, setLoadingTeams] = useState(false)

  useEffect(() => {
    fetch('/api/sports/leagues')
      .then(r => r.json())
      .then((data: League[]) => {
        // Exclude score-filter variants (ncaaf-top25, ncaaf-acc, etc.)
        const base = data.filter(l => !l.filter && !l.groups)
        setLeagues(base)
        if (base.length > 0) setLeague(base[0].id)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!league) {
      setTeams([])
      setTeamAbbr('')
      return
    }
    setLoadingTeams(true)
    fetch(`/api/sports/teams/${encodeURIComponent(league)}`)
      .then(r => r.json())
      .then((data: Team[]) => {
        setTeams(data)
        setTeamAbbr(data[0]?.abbreviation ?? '')
      })
      .catch(() => setTeams([]))
      .finally(() => setLoadingTeams(false))
  }, [league])

  const add = () => {
    if (!league || !teamAbbr) return
    const entry = `${league}:${teamAbbr}`
    if (!selected.includes(entry)) onChange([...selected, entry])
  }

  const remove = (entry: string) => onChange(selected.filter(x => x !== entry))

  const hasConferences = teams.some(t => t.conference)
  const grouped = hasConferences ? groupByConference(teams) : null
  // If all teams fall into a single un-named group, skip grouping
  const useGroups = grouped && grouped.length > 1

  const selectStyle: React.CSSProperties = { ...fieldStyle, appearance: 'none' as const }
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
          value={league}
          onChange={e => setLeague(e.target.value)}
          style={{ ...selectStyle, flex: 1 }}
        >
          {leagues.map(l => (
            <option key={l.id} value={l.id}>{l.label}</option>
          ))}
        </select>

        <select
          value={teamAbbr}
          onChange={e => setTeamAbbr(e.target.value)}
          style={{ ...selectStyle, flex: 2 }}
          disabled={!league || loadingTeams}
        >
          {loadingTeams ? (
            <option>Loading…</option>
          ) : useGroups ? (
            grouped!.map(([conf, confTeams]) => (
              <optgroup key={conf} label={conf}>
                {confTeams.map(t => (
                  <option key={t.id} value={t.abbreviation}>
                    {t.abbreviation} — {t.display_name}
                  </option>
                ))}
              </optgroup>
            ))
          ) : (
            teams.map(t => (
              <option key={t.id} value={t.abbreviation}>
                {t.abbreviation} — {t.display_name}
              </option>
            ))
          )}
        </select>

        <button type="button" onClick={add} style={addBtnStyle}>
          + ADD
        </button>
      </div>

      {selected.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {selected.map(entry => {
            const [entryLeague, entryAbbr] = entry.split(':', 2)
            const label = leagues.find(l => l.id === entryLeague)?.label ?? entryLeague.toUpperCase()
            return (
              <span key={entry} style={pillStyle}>
                <span style={{ color: C.textMuted, fontSize: F.size.xs }}>{label}</span>
                <span>{entryAbbr}</span>
                <button type="button" onClick={() => remove(entry)} style={removeBtnStyle}>
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

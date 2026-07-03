// Human-readable one-line summary of an app/module config, used in the module,
// run, and playlist lists. Renders known nested shapes (location objects,
// flight lists, city-clock lists, ...) instead of falling back to
// "[object Object]", and skips empty values so e.g. an unset "favorite teams"
// list doesn't clutter the preview.

interface LocationLike {
  latitude: number
  longitude: number
  radius_km?: number
  name?: string
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v)
}

function humanize(key: string): string {
  return key.replace(/_/g, " ")
}

function isLocationLike(v: Record<string, unknown>): boolean {
  return typeof v.latitude === "number" && typeof v.longitude === "number"
}

function formatLocation(loc: LocationLike): string {
  const name = typeof loc.name === "string" ? loc.name.trim() : ""
  const base = name || `${loc.latitude.toFixed(2)}, ${loc.longitude.toFixed(2)}`
  const radius =
    typeof loc.radius_km === "number" ? ` (${Math.round(loc.radius_km)} km)` : ""
  return `${base}${radius}`
}

/** Best-effort short label for one item of an array config value. */
function itemLabel(item: unknown): string {
  if (item == null) return ""
  if (typeof item === "string") return item.trim()
  if (typeof item === "number" || typeof item === "boolean") return String(item)
  if (isPlainObject(item)) {
    // Flight Tracker: {number, label, date}
    if (typeof item.number === "string" && item.number.trim()) return item.number.trim()
    // World Clock city / anything carrying a display name
    if (typeof item.name === "string" && item.name.trim()) return item.name.trim()
    // A bare IANA timezone (legacy world-clock rows): America/New_York -> New York
    if (typeof item.timezone === "string" && item.timezone.trim()) {
      const tz = item.timezone.trim()
      return (tz.split("/").pop() ?? tz).replace(/_/g, " ")
    }
    for (const field of ["label", "title", "team", "source"]) {
      const val = item[field]
      if (typeof val === "string" && val.trim()) return val.trim()
    }
  }
  return ""
}

/** Format a single config value; returns "" when there is nothing worth showing. */
function formatValue(v: unknown): string {
  if (v == null) return ""
  if (Array.isArray(v)) {
    const items = v.map(itemLabel).filter(Boolean)
    return items.join(", ")
  }
  if (isPlainObject(v)) {
    if (isLocationLike(v)) return formatLocation(v as unknown as LocationLike)
    return "" // avoid "[object Object]" for unrecognised objects
  }
  return String(v).trim()
}

export function configSummary(config: Record<string, unknown>): string {
  const parts: string[] = []
  for (const [k, v] of Object.entries(config)) {
    const formatted = formatValue(v)
    if (formatted) parts.push(`${humanize(k)}: ${formatted}`)
    if (parts.length >= 3) break
  }
  return parts.join(" · ") || "(no config)"
}

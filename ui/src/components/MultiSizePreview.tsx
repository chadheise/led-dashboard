import { useEffect, useRef } from 'react'
import { C, F } from '../theme'

const PANEL_SIZES = [
  { width:  64, height: 32 },
  { width: 128, height: 32 },
  { width: 196, height: 32 },
  { width: 256, height: 32 },
  { width:  64, height: 64 },
  { width: 128, height: 64 },
  { width: 196, height: 64 },
  { width: 256, height: 64 },
] as const

const SCALE = 2

// Edit mode: app_id + config → backend renders the specific module at each size
// Live mode: live=true → backend follows the active scene and re-renders on scene change
interface EditProps { appId: string; config: Record<string, unknown>; live?: never }
interface LiveProps { live: true; appId?: never; config?: never }
type Props = EditProps | LiveProps

export default function MultiSizePreview({ appId, config, live }: Props) {
  const canvasRefs = useRef<Map<string, HTMLCanvasElement>>(new Map())
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Start/update backend sizes preview
  useEffect(() => {
    if (live) {
      fetch('/api/preview/sizes/live', { method: 'POST' })
      return
    }
    if (!appId) return
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      fetch('/api/preview/sizes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ app_id: appId, config }),
      })
    }, 300)
    return () => { if (timerRef.current) clearTimeout(timerRef.current) }
  }, [live, appId, config])

  // Stop backend on unmount
  useEffect(() => {
    return () => { fetch('/api/preview/sizes', { method: 'DELETE' }).catch(() => {}) }
  }, [])

  // WebSocket — route each frame to the canvas matching its (width, height)
  useEffect(() => {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${location.host}/ws/preview/sizes`)
    ws.binaryType = 'arraybuffer'

    ws.onmessage = (evt: MessageEvent<ArrayBuffer>) => {
      const view = new DataView(evt.data)
      const w = view.getUint16(0, false)
      const h = view.getUint16(2, false)
      const canvas = canvasRefs.current.get(`${w}x${h}`)
      if (!canvas) return

      const rgb = new Uint8Array(evt.data, 4)
      const tw = w * SCALE
      const th = h * SCALE
      if (canvas.width !== tw || canvas.height !== th) {
        canvas.width = tw
        canvas.height = th
      }
      const ctx = canvas.getContext('2d')
      if (!ctx) return

      const rgba = new Uint8ClampedArray(tw * th * 4)
      for (let ly = 0; ly < h; ly++) {
        for (let lx = 0; lx < w; lx++) {
          const si = (ly * w + lx) * 3
          const r = rgb[si], g = rgb[si + 1], b = rgb[si + 2]
          for (let dy = 0; dy < SCALE; dy++) {
            for (let dx = 0; dx < SCALE; dx++) {
              const oi = ((ly * SCALE + dy) * tw + lx * SCALE + dx) * 4
              rgba[oi] = r; rgba[oi + 1] = g; rgba[oi + 2] = b; rgba[oi + 3] = 255
            }
          }
        }
      }
      ctx.putImageData(new ImageData(rgba, tw, th), 0, 0)
    }

    return () => ws.close()
  }, [])

  const rows = [32, 64].map(h => PANEL_SIZES.filter(s => s.height === h))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {rows.map(row => (
        <div key={row[0].height} style={{ display: 'flex', gap: 16, alignItems: 'flex-end' }}>
          {row.map(({ width, height }) => (
            <div
              key={`${width}x${height}`}
              style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, flexShrink: 0 }}
            >
              <canvas
                ref={el => {
                  const key = `${width}x${height}`
                  if (el) canvasRefs.current.set(key, el)
                  else canvasRefs.current.delete(key)
                }}
                width={width * SCALE}
                height={height * SCALE}
                style={{ border: `1px solid ${C.border}`, imageRendering: 'pixelated', display: 'block' }}
              />
              <span style={{ fontSize: F.size.xs, color: C.textMuted, fontFamily: F.family, letterSpacing: '0.05em' }}>
                {height}×{width}
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

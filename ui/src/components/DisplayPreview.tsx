import { useEffect, useRef, useState } from 'react'
import { C, F } from '../theme'

interface Props {
  wsUrl: string
  scale?: number
  actions?: React.ReactNode
}

type Status = 'connecting' | 'connected' | 'disconnected'

const DOT_COLOR: Record<Status, string> = {
  connecting:   C.neutral,
  connected:    C.positive,
  disconnected: C.negative,
}

// Separator color between LED pixels — simulates the dark PCB substrate
// between real LEDs. Pure near-black so any lit pixel pops against it.
const SEP = 10  // #0a0a0a

export default function DisplayPreview({ wsUrl, scale = 3, actions }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [status, setStatus] = useState<Status>('connecting')
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null)

  useEffect(() => {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${location.host}${wsUrl}`)
    ws.binaryType = 'arraybuffer'

    ws.onopen  = () => setStatus('connected')
    ws.onclose = () => setStatus('disconnected')

    ws.onmessage = (evt: MessageEvent<ArrayBuffer>) => {
      const view = new DataView(evt.data)
      const w = view.getUint16(0, false)   // logical LED columns
      const h = view.getUint16(2, false)   // logical LED rows

      const canvas = canvasRef.current
      if (!canvas) return

      const outW = w * scale
      const outH = h * scale

      if (canvas.width !== outW || canvas.height !== outH) {
        canvas.width  = outW
        canvas.height = outH
        setDims({ w, h })
      }

      const ctx = canvas.getContext('2d')
      if (!ctx) return

      const rgb  = new Uint8Array(evt.data, 4)
      const rgba = new Uint8ClampedArray(outW * outH * 4)

      if (scale <= 1) {
        // At scale=1 there is no room for a separator — render direct 1:1
        for (let i = 0; i < w * h; i++) {
          rgba[i * 4]     = rgb[i * 3]
          rgba[i * 4 + 1] = rgb[i * 3 + 1]
          rgba[i * 4 + 2] = rgb[i * 3 + 2]
          rgba[i * 4 + 3] = 255
        }
      } else {
        // Fill entire output with the separator (dark PCB) color first
        for (let i = 0; i < outW * outH; i++) {
          rgba[i * 4]     = SEP
          rgba[i * 4 + 1] = SEP
          rgba[i * 4 + 2] = SEP
          rgba[i * 4 + 3] = 255
        }

        // Each logical pixel occupies a scale×scale cell.
        // Draw it as (scale-1)×(scale-1) leaving the right and bottom edge
        // as the separator strip.
        const px = scale - 1
        for (let ly = 0; ly < h; ly++) {
          for (let lx = 0; lx < w; lx++) {
            const si = (ly * w + lx) * 3
            const r = rgb[si], g = rgb[si + 1], b = rgb[si + 2]
            for (let dy = 0; dy < px; dy++) {
              for (let dx = 0; dx < px; dx++) {
                const oi = ((ly * scale + dy) * outW + lx * scale + dx) * 4
                rgba[oi]     = r
                rgba[oi + 1] = g
                rgba[oi + 2] = b
                rgba[oi + 3] = 255
              }
            }
          }
        }
      }

      ctx.putImageData(new ImageData(rgba, outW, outH), 0, 0)
    }

    return () => ws.close()
  }, [wsUrl, scale])

  return (
    <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'stretch', gap: 8 }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        fontSize: F.size.label, color: C.textMuted, fontFamily: F.family,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: DOT_COLOR[status], display: 'inline-block' }} />
          {status}{dims ? ` · ${dims.w}×${dims.h}` : ''}
        </div>
        {actions}
      </div>
      <canvas
        ref={canvasRef}
        style={{ border: `1px solid ${C.border}`, imageRendering: 'pixelated' }}
      />
    </div>
  )
}

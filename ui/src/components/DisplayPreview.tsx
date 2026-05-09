import { useEffect, useRef, useState } from 'react'

interface Props {
  wsUrl: string
  scale?: number
}

type Status = 'connecting' | 'connected' | 'disconnected'

export default function DisplayPreview({ wsUrl, scale = 3 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const offscreenRef = useRef<OffscreenCanvas | null>(null)
  const [status, setStatus] = useState<Status>('connecting')
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null)

  useEffect(() => {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${location.host}${wsUrl}`)
    ws.binaryType = 'arraybuffer'

    ws.onopen = () => setStatus('connected')
    ws.onclose = () => setStatus('disconnected')

    ws.onmessage = (evt: MessageEvent<ArrayBuffer>) => {
      const view = new DataView(evt.data)
      const w = view.getUint16(0, false) // big-endian
      const h = view.getUint16(2, false)

      const canvas = canvasRef.current
      if (!canvas) return

      // Resize canvas and offscreen buffer only when dimensions change
      if (canvas.width !== w * scale || canvas.height !== h * scale) {
        canvas.width = w * scale
        canvas.height = h * scale
        offscreenRef.current = new OffscreenCanvas(w, h)
        setDims({ w, h })
      }

      const ctx = canvas.getContext('2d')
      const offscreen = offscreenRef.current
      if (!ctx || !offscreen) return

      // Convert packed RGB bytes → RGBA ImageData
      const rgb = new Uint8Array(evt.data, 4)
      const rgba = new Uint8ClampedArray(w * h * 4)
      for (let i = 0; i < w * h; i++) {
        rgba[i * 4]     = rgb[i * 3]
        rgba[i * 4 + 1] = rgb[i * 3 + 1]
        rgba[i * 4 + 2] = rgb[i * 3 + 2]
        rgba[i * 4 + 3] = 255
      }

      const octx = offscreen.getContext('2d')!
      octx.putImageData(new ImageData(rgba, w, h), 0, 0)

      ctx.imageSmoothingEnabled = false
      ctx.drawImage(offscreen, 0, 0, w * scale, h * scale)
    }

    return () => ws.close()
  }, [wsUrl, scale])

  const dot: Record<Status, string> = {
    connecting: '#888',
    connected: '#4f4',
    disconnected: '#f44',
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.75rem', color: '#666' }}>
        <span style={{
          width: 8, height: 8, borderRadius: '50%',
          background: dot[status], display: 'inline-block',
        }} />
        {status}{dims ? ` · ${dims.w}×${dims.h}` : ''}
      </div>
      <canvas
        ref={canvasRef}
        style={{ border: '1px solid #2a2a2a', imageRendering: 'pixelated' }}
      />
    </div>
  )
}

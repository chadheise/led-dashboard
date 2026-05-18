import DisplayPreview from '../components/DisplayPreview'
import MultiSizePreview from '../components/MultiSizePreview'

export default function Preview() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: 24, gap: 16 }}>
      <h1 style={{ fontSize: '0.85rem', letterSpacing: '0.15em', color: '#555', margin: 0 }}>
        SIMULATOR PREVIEW
      </h1>
      <DisplayPreview wsUrl="/ws/preview" scale={3} />
      {import.meta.env.DEV && <MultiSizePreview live />}
    </div>
  )
}

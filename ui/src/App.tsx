import DisplayPreview from './components/DisplayPreview'

export default function App() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: 24, gap: 16 }}>
      <h1 style={{ fontSize: '1.1rem', letterSpacing: '0.15em', color: '#aaa' }}>LED WALL PREVIEW</h1>
      <DisplayPreview wsUrl="/ws/preview" scale={3} />
    </div>
  )
}

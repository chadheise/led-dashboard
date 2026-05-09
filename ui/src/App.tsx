import { NavLink, Route, Routes } from 'react-router-dom'
import Modules from './pages/Modules'
import Playlists from './pages/Playlists'
import Preview from './pages/Preview'

const DARK = '#111'
const BORDER = '#222'

function navLinkStyle({ isActive }: { isActive: boolean }) {
  return {
    display: 'inline-block',
    padding: '10px 20px',
    fontSize: '0.75rem',
    letterSpacing: '0.12em',
    textDecoration: 'none',
    color: isActive ? '#fff' : '#555',
    borderBottom: isActive ? '2px solid #fff' : '2px solid transparent',
  }
}

export default function App() {
  return (
    <div style={{ background: DARK, minHeight: '100vh', color: '#ccc', fontFamily: 'monospace' }}>
      <nav style={{ borderBottom: `1px solid ${BORDER}`, display: 'flex', paddingLeft: 8 }}>
        <NavLink to="/" end style={navLinkStyle}>PREVIEW</NavLink>
        <NavLink to="/modules" style={navLinkStyle}>MODULES</NavLink>
        <NavLink to="/playlists" style={navLinkStyle}>PLAYLISTS</NavLink>
      </nav>
      <Routes>
        <Route path="/" element={<Preview />} />
        <Route path="/modules" element={<Modules />} />
        <Route path="/playlists" element={<Playlists />} />
      </Routes>
    </div>
  )
}

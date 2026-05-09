import { NavLink, Route, Routes } from 'react-router-dom'
import Modules from './pages/Modules'
import Playlists from './pages/Playlists'
import { C, F } from './theme'

function navLinkStyle({ isActive }: { isActive: boolean }) {
  return {
    display: 'inline-block',
    padding: '10px 20px',
    fontSize: F.size.xs,
    letterSpacing: F.tracking.wider,
    textDecoration: 'none',
    fontFamily: F.family,
    color: isActive ? C.textPrimary : C.textSecondary,
    borderBottom: isActive ? `2px solid ${C.primary}` : '2px solid transparent',
  }
}

export default function App() {
  return (
    <div style={{ background: C.bg, minHeight: '100vh', color: C.textPrimary, fontFamily: F.family }}>
      <nav style={{ borderBottom: `1px solid ${C.border}`, display: 'flex', justifyContent: 'center' }}>
        <NavLink to="/" end style={navLinkStyle}>PLAYLISTS</NavLink>
        <NavLink to="/modules" style={navLinkStyle}>MODULES</NavLink>
      </nav>
      <Routes>
        <Route path="/" element={<Playlists />} />
        <Route path="/modules" element={<Modules />} />
      </Routes>
    </div>
  )
}

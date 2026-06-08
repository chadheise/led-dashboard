import { NavLink, Route, Routes } from 'react-router-dom'
import Modules from './pages/Modules'
import Playlists from './pages/Playlists'
import Settings from './pages/Settings'
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
    <div style={{
      background: C.bg,
      color: C.textPrimary,
      fontFamily: F.family,
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }}>
      {/* Nav — fixed height, never scrolls */}
      <nav style={{ borderBottom: `1px solid ${C.border}`, display: 'flex', justifyContent: 'center', flexShrink: 0 }}>
        <NavLink to="/" end style={navLinkStyle}>PLAYLISTS</NavLink>
        <NavLink to="/modules" style={navLinkStyle}>MODULES</NavLink>
        <NavLink to="/settings" style={navLinkStyle}>SETTINGS</NavLink>
      </nav>

      {/* Route area — fills remaining height, page components manage their own scroll */}
      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <Routes>
          <Route path="/" element={<Playlists />} />
          <Route path="/modules" element={<Modules />} />
          <Route path="/modules/:id" element={<Modules />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/settings/app/:appId" element={<Settings />} />
          <Route path="/settings/library/:libId" element={<Settings />} />
        </Routes>
      </div>
    </div>
  )
}

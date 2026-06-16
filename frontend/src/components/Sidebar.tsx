import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import {
  BarChart2,
  Briefcase,
  ShieldAlert,
  PlayCircle,
  Zap,
  Activity,
  LogOut,
  User,
} from 'lucide-react';
import { useAuth } from '../App';
import styles from './Sidebar.module.css';

const NAV_ITEMS = [
  { to: '/dashboard',  label: 'Kurukshetra',  icon: BarChart2   }, // Battlefield
  { to: '/portfolio',  label: 'Karma Ledger', icon: Briefcase   }, // Deeds / Holdings
  { to: '/admin',      label: 'Dharmakshetra',icon: ShieldAlert }, // Laws / Controls
  { to: '/replay',     label: "Sanjaya's Eye",icon: PlayCircle  }, // Divine Sight / Replay
];

interface SidebarProps {
  connected?: boolean;
}

export default function Sidebar({ connected = false }: SidebarProps) {
  const { user, logout } = useAuth();
  const location = useLocation();

  // This is a simulated 24/7 exchange — always online
  const engineOnline = true;

  return (
    <aside className={styles.sidebar}>
      {/* Logo */}
      <div className={styles.logo}>
        <div className={styles.logoIcon} style={{ background: 'var(--accent-dim)', color: 'var(--accent)' }}>
          <Zap size={18} strokeWidth={2.5} />
        </div>
        <div>
          <span className={styles.logoText}>KarmaBhumi</span>
          <span className={styles.logoTagline}>Dharmic Order Engine</span>
        </div>
      </div>

      <div className={styles.divider} />

      {/* Connection status */}
      <div className={styles.statusBar}>
        <div className={styles.statusItem}>
          <span className={`${styles.dot} ${connected ? styles.dotGreen : styles.dotRed}`} />
          <span className={styles.statusLabel}>{connected ? 'Connected' : 'Connecting…'}</span>
        </div>
        <div className={styles.statusItem}>
          <span className={`${styles.dot} ${engineOnline ? styles.dotGreen : styles.dotGray}`} />
          <span className={styles.statusLabel}>{engineOnline ? 'Engine Online' : 'Engine Offline'}</span>
        </div>
      </div>

      <div className={styles.divider} />

      {/* Navigation */}
      <nav className={styles.nav}>
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `${styles.navLink} ${isActive ? styles.navLinkActive : ''}`
            }
          >
            <Icon size={17} strokeWidth={1.8} />
            <span>{label}</span>
            {to === '/admin' && user?.is_admin && (
              <span className={styles.adminBadge}>ADMIN</span>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Live Pulse */}
      <div className={styles.pulseSection}>
        <Activity size={14} className={styles.pulseIcon} />
        <span className={styles.pulseText}>Live Engine</span>
        <span className={styles.pulseDot} />
      </div>

      <div className={styles.divider} />

      {/* User section */}
      <div className={styles.userSection}>
        {user ? (
          <>
            <div className={styles.userAvatar}>
              {user.username.charAt(0).toUpperCase()}
            </div>
            <div className={styles.userInfo}>
              <span className={styles.userName}>{user.username}</span>
              <span className={styles.userEmail}>{user.email}</span>
            </div>
            <button className={styles.logoutBtn} onClick={logout} title="Logout">
              <LogOut size={15} />
            </button>
          </>
        ) : (
          <div className={styles.userAvatar}>
            <User size={16} />
          </div>
        )}
      </div>
    </aside>
  );
}

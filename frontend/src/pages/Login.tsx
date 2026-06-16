import React, { useState } from 'react';
import { useAuthActions } from '../hooks/useAuth';
import { Zap, Shield, Sparkles, User, Key, Mail } from 'lucide-react';
import styles from './Login.module.css';

const QUICK_CREDS = [
  {
    name: 'Krishna (Admin)',
    email: 'krishna@karmabhumi.com',
    pass: 'KrishnaPassword123!',
    role: 'Admin',
    color: '#2980b9', // peacock feather blue
  },
  {
    name: 'Arjuna (Trader)',
    email: 'arjuna@karmabhumi.com',
    pass: 'ArjunaPassword123!',
    role: 'Trader 1',
    color: '#ff9f43', // saffron
  },
  {
    name: 'Karna (Trader)',
    email: 'karna@karmabhumi.com',
    pass: 'KarnaPassword123!',
    role: 'Trader 2',
    color: '#ea2027', // blood red
  },
];

export default function Login() {
  const { login, register, loading } = useAuthActions();
  const [isRegister, setIsRegister] = useState(false);
  
  // Form state
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isRegister) {
      await register({ email, username: username || email.split('@')[0], password });
    } else {
      await login({ email, password });
    }
  };

  const handleQuickLogin = async (qEmail: string, qPass: string) => {
    await login({ email: qEmail, password: qPass });
  };

  return (
    <div className={styles.container}>
      {/* Background dust particle overlay effect */}
      <div className={styles.bgOverlay} />

      <div className={styles.card}>
        <div className={styles.header}>
          <div className={styles.logoIcon}>
            <Zap size={28} />
          </div>
          <h1 className={styles.title}>KarmaBhumi</h1>
          <p className={styles.subtitle}>The Dharmic Order Matching Engine</p>
        </div>

        <form className={styles.form} onSubmit={handleSubmit}>
          <div className={styles.inputGroup}>
            <label className={styles.label}>Email Address</label>
            <div className={styles.inputWrapper}>
              <Mail className={styles.inputIcon} size={16} />
              <input
                type="email"
                required
                className={styles.input}
                placeholder="enter your email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
          </div>

          {isRegister && (
            <div className={styles.inputGroup}>
              <label className={styles.label}>Warrior Username</label>
              <div className={styles.inputWrapper}>
                <User className={styles.inputIcon} size={16} />
                <input
                  type="text"
                  required
                  className={styles.input}
                  placeholder="e.g. arjuna_99"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </div>
            </div>
          )}

          <div className={styles.inputGroup}>
            <label className={styles.label}>Secret Key (Password)</label>
            <div className={styles.inputWrapper}>
              <Key className={styles.inputIcon} size={16} />
              <input
                type="password"
                required
                className={styles.input}
                placeholder="enter password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
          </div>

          <button type="submit" disabled={loading} className={styles.submitBtn}>
            {loading ? (
              <span className={styles.spinner} />
            ) : isRegister ? (
              'Enter the Battlefield (Register)'
            ) : (
              'Ascend to Chariot (Log In)'
            )}
          </button>
        </form>

        <div className={styles.switch}>
          <span>
            {isRegister ? 'Already a warrior?' : 'New to Kurukshetra?'}
          </span>
          <button
            type="button"
            className={styles.switchBtn}
            onClick={() => setIsRegister(!isRegister)}
          >
            {isRegister ? 'Log In' : 'Register'}
          </button>
        </div>

        <div className={styles.divider}>
          <span className={styles.dividerLine} />
          <span className={styles.dividerText}>Quick Summon Warriors</span>
          <span className={styles.dividerLine} />
        </div>

        <div className={styles.quickSummon}>
          {QUICK_CREDS.map((cred) => (
            <button
              key={cred.name}
              type="button"
              className={styles.summonCard}
              style={{ '--accent-color': cred.color } as React.CSSProperties}
              onClick={() => handleQuickLogin(cred.email, cred.pass)}
              disabled={loading}
            >
              <div className={styles.summonIcon} style={{ backgroundColor: `${cred.color}20`, color: cred.color }}>
                {cred.role === 'Admin' ? <Shield size={16} /> : <Sparkles size={16} />}
              </div>
              <div className={styles.summonInfo}>
                <span className={styles.summonName}>{cred.name}</span>
                <span className={styles.summonRole}>{cred.role}</span>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

import React, { useState, useEffect } from 'react';
import { api, AdminMetrics, CircuitBreaker, SystemUser } from '../api/client';
import toast from 'react-hot-toast';
import styles from './Admin.module.css';

export default function Admin() {
  const [metrics, setMetrics] = useState<AdminMetrics | null>(null);
  const [cbs, setCbs] = useState<CircuitBreaker[]>([]);
  const [users, setUsers] = useState<SystemUser[]>([]);
  const [activities, setActivities] = useState<{ timestamp: string; event: string; severity: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);

  // Risk limit inputs
  const [posLimit, setPosLimit] = useState(1000);
  const [expLimit, setExpLimit] = useState(10000000);

  const fetchAdminData = async () => {
    try {
      const [metricsData, cbsData, usersData, activityData] = await Promise.all([
        api.admin.metrics().catch(() => null),
        api.admin.circuitBreakers().catch(() => []),
        api.admin.users().catch(() => []),
        api.admin.activityLog().catch(() => []),
      ]);

      if (metricsData) setMetrics(metricsData);
      setCbs(cbsData);
      setUsers(usersData);
      setActivities(activityData);
    } catch (err) {
      console.error('Failed to fetch admin data', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAdminData();
    const interval = setInterval(fetchAdminData, 3000);
    return () => clearInterval(interval);
  }, []);

  const handleCBAction = async (symbol: string, action: 'pause' | 'resume') => {
    try {
      if (action === 'pause') {
        await api.admin.pause(symbol);
        toast.success(`Halted trading for ${symbol}`);
      } else {
        await api.admin.resume(symbol);
        toast.success(`Resumed trading for ${symbol}`);
      }
      fetchAdminData();
    } catch (err) {
      toast.error(`Failed to ${action} trading for ${symbol}`);
    }
  };

  const handleUpdateRisk = async (e: React.FormEvent) => {
    e.preventDefault();
    setUpdating(true);
    try {
      await api.admin.updateRiskLimits({
        symbol: 'AAPL',
        price_change_pct: posLimit / 100,
        window_seconds: 300,
        enabled: true,
      });
      toast.success('Risk limits updated successfully');
    } catch (err) {
      toast.error('Failed to update risk limits');
    } finally {
      setUpdating(false);
    }
  };

  if (loading && !metrics) {
    return <div className={styles.loading}>Loading Admin Console…</div>;
  }

  return (
    <div className={styles.container}>
      <h1 className={styles.title}>Exchange Control Room (Admin)</h1>

      {/* Metrics Row */}
      <div className={styles.grid3}>
        <div className={styles.card}>
          <div className={styles.cardHeader}>Engine Load</div>
          <div className={styles.metricRow}>
            <div>
              <span className={styles.metricVal}>{metrics?.orders_per_sec.toFixed(1) ?? '0.0'}</span>
              <span className={styles.metricUnit}> msg/s</span>
            </div>
            <div className={styles.metricLabel}>Orders Submitted</div>
          </div>
          <div className={styles.metricRow}>
            <div>
              <span className={styles.metricVal}>{metrics?.trades_per_sec.toFixed(1) ?? '0.0'}</span>
              <span className={styles.metricUnit}> trades/s</span>
            </div>
            <div className={styles.metricLabel}>Matches Found</div>
          </div>
        </div>

        <div className={styles.card}>
          <div className={styles.cardHeader}>Latency Profiles</div>
          <div className={styles.latencyGrid}>
            <div>
              <div className={styles.latVal}>{(metrics?.latency_p50 ?? 0 / 1e6).toFixed(3)} ms</div>
              <div className={styles.latLabel}>P50 Latency</div>
            </div>
            <div>
              <div className={styles.latVal}>{(metrics?.latency_p95 ?? 0 / 1e6).toFixed(3)} ms</div>
              <div className={styles.latLabel}>P95 Latency</div>
            </div>
            <div>
              <div className={styles.latVal}>{(metrics?.latency_p99 ?? 0 / 1e6).toFixed(3)} ms</div>
              <div className={styles.latLabel}>P99 Latency</div>
            </div>
          </div>
        </div>

        <div className={styles.card}>
          <div className={styles.cardHeader}>Session Health</div>
          <div className={styles.metricRow}>
            <div>
              <span className={styles.metricVal}>{metrics?.active_websockets ?? 0}</span>
            </div>
            <div className={styles.metricLabel}>Live WebSocket Feeds</div>
          </div>
          <div className={styles.metricRow}>
            <div>
              <span className={styles.metricVal}>{metrics?.queue_depth ?? 0}</span>
            </div>
            <div className={styles.metricLabel}>Message Queue Backlog</div>
          </div>
        </div>
      </div>

      <div className={styles.mainContent}>
        {/* Left Side: Circuit Breakers & User Management */}
        <div className={styles.leftCol}>
          {/* Circuit Breakers */}
          <div className={styles.sectionCard}>
            <div className={styles.sectionHeader}>Market Circuit Breakers</div>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Current State</th>
                  <th>Reason</th>
                  <th>Control Action</th>
                </tr>
              </thead>
              <tbody>
                {cbs.map((cb) => (
                  <tr key={cb.symbol}>
                    <td className={styles.bold}>{cb.symbol}</td>
                    <td>
                      <span className={`${styles.statusBadge} ${cb.status === 'active' ? styles.green : styles.red}`}>
                        {cb.status === 'active' ? 'Trading Enabled' : 'Halted'}
                      </span>
                    </td>
                    <td className={styles.muted}>{cb.reason || 'N/A'}</td>
                    <td>
                      {cb.status === 'active' ? (
                        <button
                          onClick={() => handleCBAction(cb.symbol, 'pause')}
                          className={`${styles.btn} ${styles.btnDanger}`}
                        >
                          Halt Market
                        </button>
                      ) : (
                        <button
                          onClick={() => handleCBAction(cb.symbol, 'resume')}
                          className={`${styles.btn} ${styles.btnSuccess}`}
                        >
                          Resume Market
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* User Management */}
          <div className={styles.sectionCard}>
            <div className={styles.sectionHeader}>Active Ledger Balances</div>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>User ID</th>
                  <th>Account User</th>
                  <th>Ledger Cash</th>
                  <th>Privilege</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.user_id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-dim)' }}>
                      {user.user_id.slice(0, 8)}…
                    </td>
                    <td className={styles.bold}>{user.email}</td>
                    <td className={styles.greenText}>${user.balance.toLocaleString('en-US', { minimumFractionDigits: 2 })}</td>
                    <td>
                      <span className={`${styles.badge} ${user.is_admin ? styles.badgeAdmin : styles.badgeUser}`}>
                        {user.is_admin ? 'Admin' : 'Trader'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Right Side: Risk Limits & Event Logs */}
        <div className={styles.rightCol}>
          {/* Risk Limits */}
          <div className={styles.sectionCard}>
            <div className={styles.sectionHeader}>Engine Risk Limits</div>
            <form onSubmit={handleUpdateRisk} className={styles.form}>
              <div className={styles.formGroup}>
                <label>Max Position Limit (per symbol)</label>
                <input
                  type="number"
                  value={posLimit}
                  onChange={(e) => setPosLimit(parseInt(e.target.value))}
                  required
                />
              </div>
              <div className={styles.formGroup}>
                <label>Max Order Exposure Limit (₹)</label>
                <input
                  type="number"
                  value={expLimit}
                  onChange={(e) => setExpLimit(parseInt(e.target.value))}
                  required
                />
              </div>
              <button type="submit" disabled={updating} className={styles.submitBtn}>
                {updating ? 'Updating Limits…' : 'Deploy Global Risk Settings'}
              </button>
            </form>
          </div>

          {/* Activity Logs */}
          <div className={styles.sectionCard}>
            <div className={styles.sectionHeader}>Risk & Circuit Breaker Logs</div>
            <div className={styles.logsBox}>
              {activities.length === 0 ? (
                <div className={styles.noLogs}>No system anomalies detected.</div>
              ) : (
                activities.map((act, index) => (
                  <div key={index} className={`${styles.logLine} ${styles[act.severity]}`}>
                    <span className={styles.logTime}>{new Date(act.timestamp).toLocaleTimeString()}</span>
                    <span className={styles.logText}>{act.event}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

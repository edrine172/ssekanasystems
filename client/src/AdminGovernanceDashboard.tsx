import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import {
  Activity, AlertTriangle, ArrowRight, Building2, ChevronRight,
  CircleAlert, Clock3, Database, Download, ExternalLink, LayoutDashboard,
  LoaderCircle, LogOut, Search, Settings, Shield, ShieldCheck,
  Upload, UserRound, Users, X, type LucideIcon,
} from 'lucide-react';
import {
  AdministratorSessionExpiredError, api, formatCurrency as currency, type AccessDashboardData, type AccessUser,
  type SecurityAuditEvent, type SettingsAuditEvent, type StaffDashboardData,
  type SystemSettingsData,
} from './api';
const UsersDashboard = lazy(() => import('./UsersDashboard'));
const SettingsDashboard = lazy(() => import('./SettingsDashboard'));

type AdminSection = 'overview' | 'access' | 'team' | 'departments' | 'audit' | 'backup' | 'settings';
type AuditRow = { id: string; actor: string; action: string; target: string; date: string; source: string };

const sections: Array<{ id: AdminSection; label: string; icon: LucideIcon }> = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'access', label: 'User & Access', icon: Shield },
  { id: 'team', label: 'Manage Team', icon: Users },
  { id: 'departments', label: 'Departments', icon: Building2 },
  { id: 'audit', label: 'Audit & Compliance', icon: ShieldCheck },
  { id: 'backup', label: 'Backup & Recovery', icon: Database },
  { id: 'settings', label: 'System Settings', icon: Settings },
];

function displayName(user: AccessUser) {
  return user.display_name || [user.first_name, user.last_name].filter(Boolean).join(' ') || user.username;
}

function formatDate(value: string) {
  return new Date(value).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

function AdminSignIn({ onSignedIn, error, notice }: {
  onSignedIn: (username: string, password: string) => Promise<void>;
  error: string;
  notice: string;
}) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState('');

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setFormError('');
    try {
      await onSignedIn(username, password);
    } catch (cause) {
      setFormError(cause instanceof Error ? cause.message : 'Administrator sign-in failed.');
    } finally {
      setBusy(false);
    }
  }

  return <main className="governance-login-page">
    <form className="governance-login-card" onSubmit={(event) => void submit(event)}>
      <span className="governance-brand-mark"><ShieldCheck size={20}/></span>
      <span className="governance-eyebrow">STOCKPULSE · ADMIN GOVERNANCE</span>
      <h1>Administrator sign-in</h1>
      <p>This separate administration portal is restricted to Django superusers.</p>
      {notice && <p className="governance-info" role="status">{notice}</p>}
      <label>Username<input autoComplete="username" required value={username} onChange={(event) => setUsername(event.target.value)}/></label>
      <label>Password<input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)}/></label>
      {(formError || error) && <p className="governance-error">{formError || error}</p>}
      <button type="submit" disabled={busy}>{busy ? <><LoaderCircle size={15}/>Signing in…</> : 'Sign in securely'}</button>
    </form>
  </main>;
}

function Metric({ label, value, detail, icon: Icon, tone = 'blue' }: {
  label: string;
  value: string | number;
  detail: string;
  icon: LucideIcon;
  tone?: 'blue' | 'green' | 'amber' | 'red';
}) {
  return <article className={`governance-metric tone-${tone}`}>
    <div className="governance-metric-label"><span>{label}</span><i><Icon size={15}/></i></div>
    <strong>{value}</strong>
    <small>{detail}</small>
  </article>;
}

function PageHeading({ eyebrow, title, description, actions }: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: React.ReactNode;
}) {
  return <header className="governance-page-heading">
    <div><span className="governance-eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>
    {actions && <div className="governance-heading-actions">{actions}</div>}
  </header>;
}

function downloadAudit(rows: AuditRow[]) {
  const header = ['Timestamp', 'Actor', 'Action', 'Target', 'Source'];
  const escape = (value: string) => `"${value.replace(/"/g, '""')}"`;
  const csv = [header, ...rows.map((row) => [row.date, row.actor, row.action, row.target, row.source])]
    .map((row) => row.map(escape).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'stockpulse-admin-audit.csv';
  link.click();
  URL.revokeObjectURL(url);
}

export default function AdminGovernanceDashboard() {
  const [admin, setAdmin] = useState<AccessUser | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [error, setError] = useState('');
  const [adminNotice, setAdminNotice] = useState('');
  const [activeSection, setActiveSection] = useState<AdminSection>('overview');
  const [search, setSearch] = useState('');
  const [accessData, setAccessData] = useState<AccessDashboardData | null>(null);
  const [staffData, setStaffData] = useState<StaffDashboardData | null>(null);
  const [settingsData, setSettingsData] = useState<SystemSettingsData | null>(null);
  const [loadingData, setLoadingData] = useState(false);
  const [dataError, setDataError] = useState('');
  const [reloadVersion, setReloadVersion] = useState(0);
  const [backupBusy, setBackupBusy] = useState(false);
  const [backupError, setBackupError] = useState('');
  const [backupSuccess, setBackupSuccess] = useState('');
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [restoreConfirmed, setRestoreConfirmed] = useState(false);
  const [restoreBusy, setRestoreBusy] = useState(false);
  const [restoreError, setRestoreError] = useState('');
  const [restoreInputKey, setRestoreInputKey] = useState(0);

  useEffect(() => {
    const previousTitle = document.title;
    document.title = 'StockPulse Admin Governance';
    return () => { document.title = previousTitle; };
  }, []);

  useEffect(() => {
    let current = true;
    void api.accessSession().then(({ user }) => {
      if (current) {
        if (user.is_superuser) setAdmin(user);
        else setError('This portal requires a Django superuser account.');
      }
    }).catch((cause) => {
      if (current && !/workspace sign-in required|administrator sign-in required|authentication credentials/i.test(cause instanceof Error ? cause.message : '')) {
        setError(cause instanceof Error ? cause.message : 'Administrator session could not be checked.');
      }
    }).finally(() => { if (current) setCheckingSession(false); });
    return () => { current = false; };
  }, []);

  useEffect(() => {
    if (!admin) return;
    let current = true;
    const needsAccess = activeSection === 'overview' || activeSection === 'access' || activeSection === 'audit';
    const needsStaff = activeSection === 'overview' || activeSection === 'team' || activeSection === 'departments';
    const needsSettings = activeSection === 'overview' || activeSection === 'audit';
    setLoadingData(true);
    setDataError('');
    const loads: Array<Promise<void>> = [];
    if (needsAccess) loads.push(api.accessDashboard().then((data) => { if (current) setAccessData(data); }));
    if (needsStaff) loads.push(api.staffDashboard().then((data) => { if (current) setStaffData(data); }));
    if (needsSettings) loads.push(api.systemSettings().then((data) => { if (current) setSettingsData(data); }));
    void Promise.all(loads).catch((cause) => {
      if (current) setDataError(cause instanceof Error ? cause.message : 'Administration data could not be loaded.');
    }).finally(() => { if (current) setLoadingData(false); });
    return () => { current = false; };
  }, [activeSection, admin, reloadVersion]);

  async function signIn(username: string, password: string) {
    const result = await api.accessLogin(username, password);
    if (!result.user.is_superuser) {
      await api.accessLogout();
      throw new Error('This portal requires a Django superuser account.');
    }
    setError('');
    setAdminNotice('');
    setAdmin(result.user);
  }

  async function downloadDatabaseBackup() {
    if (backupBusy || restoreBusy) return;
    setBackupBusy(true);
    setBackupError('');
    setBackupSuccess('');
    try {
      const { blob, filename } = await api.downloadSystemBackup();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setBackupSuccess(`Database backup downloaded: ${filename}`);
    } catch (cause) {
      if (cause instanceof AdministratorSessionExpiredError) {
        setAdminNotice(cause.message);
        setAdmin(null);
      } else {
        setBackupError(cause instanceof Error ? cause.message : 'Database backup could not be created.');
      }
    } finally {
      setBackupBusy(false);
    }
  }

  async function restoreDatabaseBackup(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!restoreFile || !restoreConfirmed || backupBusy || restoreBusy) return;
    setRestoreBusy(true);
    setRestoreError('');
    setBackupSuccess('');
    try {
      const { blob, filename, restoredRecords } = await api.restoreSystemBackup(restoreFile);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setRestoreFile(null);
      setRestoreConfirmed(false);
      setRestoreInputKey((key) => key + 1);
      setAdminNotice(`Restore completed (${restoredRecords.toLocaleString()} fixture records). The pre-restore safety backup was downloaded as ${filename}. Sign in again using an active superuser account from the restored backup.`);
      setAdmin(null);
    } catch (cause) {
      if (cause instanceof AdministratorSessionExpiredError) {
        setAdminNotice(cause.message);
        setAdmin(null);
      } else {
        setRestoreError(cause instanceof Error ? cause.message : 'Database restore failed; the current database was left unchanged.');
      }
    } finally {
      setRestoreBusy(false);
    }
  }

  async function signOut() {
    try {
      await api.accessLogout();
    } finally {
      window.location.assign('/');
    }
  }

  const auditRows = useMemo<AuditRow[]>(() => {
    const securityRows: AuditRow[] = (accessData?.audit_log ?? []).map((event: SecurityAuditEvent) => ({
      id: `security-${event.id}`,
      actor: event.actor_name,
      action: event.action,
      target: `${event.target_type}${event.target_id ? ` · ${event.target_id}` : ''}`,
      date: event.created_at,
      source: 'Security audit',
    }));
    const settingsRows: AuditRow[] = (settingsData?.audit_log ?? []).map((event: SettingsAuditEvent) => ({
      id: `settings-${event.id}`,
      actor: event.actor_name,
      action: event.action,
      target: `Settings · ${event.target_id}`,
      date: event.created_at,
      source: 'Settings audit',
    }));
    return [...securityRows, ...settingsRows].sort((a, b) => b.date.localeCompare(a.date));
  }, [accessData, settingsData]);
  const visibleAuditRows = useMemo(() => {
    const term = search.trim().toLowerCase();
    return auditRows.filter((row) => !term || `${row.actor} ${row.action} ${row.target} ${row.source}`.toLowerCase().includes(term));
  }, [auditRows, search]);

  const departments = staffData?.departments ?? [];
  const staff = staffData?.workers ?? [];
  const filteredStaff = staff.filter((worker) =>
    `${worker.full_name} ${worker.employee_number} ${worker.job_title} ${worker.department}`
      .toLowerCase().includes(search.trim().toLowerCase()));

  if (checkingSession) return <main className="governance-login-page"><div className="governance-loading"><LoaderCircle size={18}/>Checking administrator session…</div></main>;
  if (!admin) return <AdminSignIn onSignedIn={signIn} error={error} notice={adminNotice}/>;

  return <div className="governance-shell">
    <aside className="governance-sidebar">
      <a className="governance-logo" href="/" aria-label="Return to StockPulse operations"><span><ShieldCheck size={18}/></span><b>StockPulse<small>ADMIN GOVERNANCE</small></b></a>
      <span className="governance-nav-label">ADMINISTRATION &amp; GOVERNANCE</span>
      <nav aria-label="Administration dashboards">{sections.map(({ id, label, icon: Icon }) =>
        <button type="button" key={id} className={activeSection === id ? 'is-active' : ''} aria-current={activeSection === id ? 'page' : undefined} onClick={() => { setActiveSection(id); setSearch(''); }}>
          <Icon size={15}/><span>{label}</span>
        </button>)}</nav>
      <a className="governance-back-link" href="/"><ArrowRight size={14}/>Return to operations</a>
      <div className="governance-sidebar-status"><i/><span><strong>Administration portal</strong><small>Live application data</small></span></div>
    </aside>

    <main className="governance-main">
      <div className="governance-topbar">
        {['team', 'departments', 'audit'].includes(activeSection) && <label className="governance-global-search"><Search size={15}/><input aria-label={`Filter ${activeLabel(activeSection)}`} placeholder="Filter staff, departments, or events…" value={search} onChange={(event) => setSearch(event.target.value)}/>{search && <button type="button" aria-label="Clear search" onClick={() => setSearch('')}><X size={13}/></button>}</label>}
        <span className="governance-live"><i/>Connected to StockPulse</span>
        <div className="governance-admin-chip"><span>{displayName(admin).slice(0, 1).toUpperCase()}</span><div><strong>{displayName(admin)}</strong><small>Superuser</small></div></div>
        <button type="button" className="governance-signout" onClick={() => void signOut()} aria-label="Sign out"><LogOut size={15}/></button>
      </div>

      {dataError && <div className="governance-alert" role="alert"><CircleAlert size={16}/><span>{dataError}</span><button type="button" onClick={() => setReloadVersion((version) => version + 1)}>Retry</button><button type="button" onClick={() => setDataError('')} aria-label="Dismiss error"><X size={14}/></button></div>}
      {loadingData && <div className="governance-loading-inline"><LoaderCircle size={15}/>Refreshing live administration data…</div>}

      {activeSection === 'overview' && <section className="governance-content">
        <PageHeading eyebrow="GOVERNANCE TIER · SUPERUSER" title="Admin & System Overview" description="A live view of user access, workforce structure, configuration and recorded administration activity." actions={<a className="governance-button secondary" href="/"><ExternalLink size={14}/>Open operations</a>}/>
        <div className="governance-metric-grid">
          <Metric label="IDENTITIES & ACCESS" value={accessData?.total_users ?? '—'} detail={`${accessData?.active_users ?? '—'} active · ${accessData?.role_count ?? '—'} roles`} icon={Users}/>
          <Metric label="WORKFORCE" value={staffData?.summary.active_workers ?? '—'} detail={`${departments.length} recorded departments`} icon={Building2} tone="green"/>
          <Metric label="SECURITY POSTURE" value={settingsData ? settingsData.settings.security.require_two_factor ? '2FA on' : '2FA off' : '—'} detail={settingsData ? `${settingsData.settings.security.audit_retention_days} day audit retention` : 'Settings status unavailable'} icon={ShieldCheck} tone={settingsData?.settings.security.require_two_factor ? 'green' : 'amber'}/>
          <Metric label="RECENT AUDIT EVENTS" value={auditRows.length} detail="Events returned by current audit APIs" icon={Activity}/>
          <Metric label="DATABASE BACKUP" value="Available" detail="Download a compressed system data backup" icon={Database} tone="green"/>
        </div>
        <section className="governance-panel">
          <div className="governance-panel-heading"><div><span className="governance-panel-icon"><Activity size={16}/></span><div><h2>Recent administration activity</h2><p>Latest audit records currently available from the application.</p></div></div><button type="button" className="governance-text-button" onClick={() => setActiveSection('audit')}>View audit trail <ChevronRight size={14}/></button></div>
          <AuditTable rows={visibleAuditRows.slice(0, 5)} empty={search ? 'No audit events match this filter.' : 'No audit events are available from the connected audit APIs.'}/>
        </section>
        <div className="governance-overview-links">{sections.filter((section) => section.id !== 'overview').map(({ id, label, icon: Icon }) =>
          <button type="button" key={id} onClick={() => setActiveSection(id)}><Icon size={16}/><span>{label}</span><ChevronRight size={14}/></button>)}</div>
      </section>}

      {activeSection === 'access' && <section className="governance-content governance-embedded"><Suspense fallback={<div className="governance-loading-inline"><LoaderCircle size={15}/>Loading access controls…</div>}><UsersDashboard onSignOut={signOut}/></Suspense></section>}

      {activeSection === 'team' && <section className="governance-content">
        <PageHeading eyebrow="WORKFORCE DIRECTORY" title="Manage Team" description="Review worker records and status from the existing staff directory."/>
        <div className="governance-metric-grid governance-metric-grid-3">
          <Metric label="ACTIVE WORKERS" value={staffData?.summary.active_workers ?? '—'} detail="Current active staff records" icon={Users} tone="green"/>
          <Metric label="ON LEAVE" value={staffData?.summary.on_leave_workers ?? '—'} detail="Staff marked on leave" icon={Clock3} tone="amber"/>
          <Metric label="INACTIVE" value={staffData?.summary.inactive_workers ?? '—'} detail="Inactive staff records" icon={UserRound}/>
        </div>
        <section className="governance-panel">
          <div className="governance-panel-heading"><div><span className="governance-panel-icon"><Users size={16}/></span><div><h2>Team directory</h2><p>{filteredStaff.length} of {staff.length} staff records</p></div></div></div>
          <StaffTable workers={filteredStaff}/>
        </section>
      </section>}

      {activeSection === 'departments' && <section className="governance-content">
        <PageHeading eyebrow="ORGANIZATION STRUCTURE" title="Departments" description="Department names, staff counts and payroll estimates from the staff dashboard. Department budgets and cost centers are not configured in this application."/>
        <div className="governance-metric-grid governance-metric-grid-3">
          <Metric label="RECORDED DEPARTMENTS" value={departments.length} detail="Distinct departments in staff records" icon={Building2}/>
          <Metric label="WORKERS IN DEPARTMENTS" value={departments.reduce((sum, item) => sum + item.workers, 0)} detail="Staff grouped by department" icon={Users} tone="green"/>
          <Metric label="ESTIMATED GROSS PAYROLL" value={currency(departments.reduce((sum, item) => sum + Number(item.gross_total), 0))} detail="Current selected payroll period" icon={Activity}/>
        </div>
        <section className="governance-department-grid">{departments.filter((item) => item.name.toLowerCase().includes(search.trim().toLowerCase())).map((department) => {
          const members = staff.filter((worker) => worker.department === department.name);
          return <article className="governance-department-card" key={department.name}>
            <div className="governance-department-icon"><Building2 size={18}/></div>
            <span className="governance-eyebrow">DEPARTMENT</span>
            <h2>{department.name}</h2>
            <div className="governance-department-stats"><span><small>TEAM SIZE</small><strong>{department.workers}</strong></span><span><small>EST. GROSS PAYROLL</small><strong>{currency(department.gross_total)}</strong></span></div>
            <div className="governance-member-list">{members.slice(0, 4).map((member) => <span key={member.id}><i>{member.full_name.slice(0, 1).toUpperCase()}</i>{member.full_name}<small>{member.job_title}</small></span>)}{members.length > 4 && <small>+{members.length - 4} more team members</small>}</div>
          </article>;
        })}{!departments.length && !loadingData && <div className="governance-empty">No department records are available yet. Add departments to staff profiles to see them here.</div>}</section>
      </section>}

      {activeSection === 'audit' && <section className="governance-content">
        <PageHeading eyebrow="SECURITY & COMPLIANCE" title="Audit & Compliance" description="Review security and settings audit records returned by the existing application APIs. No cryptographic ledger verification is available." actions={<button type="button" className="governance-button secondary" disabled={!visibleAuditRows.length} onClick={() => downloadAudit(visibleAuditRows)}><Download size={14}/>Export available audit records</button>}/>
        <div className="governance-metric-grid governance-metric-grid-3">
          <Metric label="AVAILABLE AUDIT EVENTS" value={auditRows.length} detail="Current API result set" icon={Activity}/>
          <Metric label="SECURITY EVENTS" value={accessData?.audit_log.length ?? '—'} detail="Access and security event records" icon={ShieldCheck} tone="green"/>
          <Metric label="SETTINGS CHANGES" value={settingsData?.audit_log.length ?? '—'} detail="Configuration change records" icon={Settings}/>
        </div>
        <section className="governance-panel">
          <div className="governance-panel-heading"><div><span className="governance-panel-icon"><ShieldCheck size={16}/></span><div><h2>Audit event ledger</h2><p>Source: application security and system settings audit APIs.</p></div></div></div>
          <AuditTable rows={visibleAuditRows} empty={search ? 'No audit events match this filter.' : 'No audit events are available from the connected audit APIs.'}/>
        </section>
        <div className="governance-notice"><AlertTriangle size={16}/><p><strong>Compliance scope</strong><br/>This view reports only real audit records exposed by the application. It does not claim external certifications, immutable storage, cryptographic verification, or controls that are not implemented.</p></div>
      </section>}

      {activeSection === 'backup' && <section className="governance-content">
        <PageHeading eyebrow="BUSINESS CONTINUITY" title="Backup & Recovery" description="Create and download a compressed backup of the connected StockPulse application database."/>
        <div className="governance-backup-card">
          <span className="governance-backup-icon"><Database size={23}/></span>
          <span className="governance-eyebrow">DATABASE EXPORT</span>
          <h2>Download a system data backup</h2>
          <p>Exports records from the connected application database, including inventory, sales, finance, staff, user accounts, audit history, and system settings. The export is a compressed JSON fixture (.json.gz).</p>
          <button type="button" className="governance-button primary" disabled={backupBusy || restoreBusy} onClick={() => void downloadDatabaseBackup()}>{backupBusy ? <><LoaderCircle size={14}/>Creating backup…</> : <><Download size={14}/>Create &amp; download backup</>}</button>
          {backupError && <p className="governance-backup-error" role="alert">{backupError}</p>}
          {backupSuccess && <p className="governance-backup-success" role="status">{backupSuccess}</p>}
        </div>
        <div className="governance-backup-card">
          <span className="governance-backup-icon"><Upload size={23}/></span>
          <span className="governance-eyebrow">DATABASE RESTORE</span>
          <h2>Import a system data backup</h2>
          <p>Restore a StockPulse database backup in JSON or compressed .json.gz format. The current database is replaced only after the uploaded fixture is successfully loaded.</p>
          <form className="governance-restore-form" onSubmit={(event) => void restoreDatabaseBackup(event)}>
            <label className="governance-restore-file">Choose backup file<input key={restoreInputKey} type="file" accept=".json,.gz,application/json,application/gzip" onChange={(event) => { setRestoreFile(event.target.files?.[0] ?? null); setRestoreConfirmed(false); setRestoreError(''); }} disabled={backupBusy || restoreBusy}/></label>
            {restoreFile && <p className="governance-restore-selected">Selected: {restoreFile.name} ({(restoreFile.size / 1024 / 1024).toFixed(2)} MB)</p>}
            <label className="governance-restore-confirm"><input type="checkbox" checked={restoreConfirmed} onChange={(event) => setRestoreConfirmed(event.target.checked)} disabled={!restoreFile || backupBusy || restoreBusy}/>I understand this will replace all current database records with the uploaded backup. A pre-restore safety backup will be downloaded automatically. The backup must include an active superuser account.</label>
            <button type="submit" className="governance-button danger" disabled={!restoreFile || !restoreConfirmed || backupBusy || restoreBusy}>{restoreBusy ? <><LoaderCircle size={14}/>Validating and restoring…</> : <><Upload size={14}/>Restore database from backup</>}</button>
            {restoreError && <p className="governance-backup-error" role="alert">{restoreError}</p>}
          </form>
        </div>
        <div className="governance-notice"><AlertTriangle size={16}/><p><strong>Protect your backups</strong><br/>Backup files contain sensitive business data and password hashes. Restore replaces current database contents; if validation or import fails, the database transaction is rolled back. Active login sessions are excluded. Backups do not include application code, uploaded files, or hosting environment secrets. The pre-restore safety copy is downloaded to this browser and should be stored securely. You may need to sign in again after a restore.</p></div>
      </section>}

      {activeSection === 'settings' && <section className="governance-content governance-embedded"><Suspense fallback={<div className="governance-loading-inline"><LoaderCircle size={15}/>Loading system settings…</div>}><SettingsDashboard onNavigate={() => undefined} onSignOut={signOut}/></Suspense></section>}
    </main>
  </div>;
}

function activeLabel(section: AdminSection) {
  return sections.find((item) => item.id === section)?.label ?? 'dashboard';
}

function StaffTable({ workers }: { workers: StaffDashboardData['workers'] }) {
  return <div className="governance-table-scroll"><table className="governance-table"><thead><tr><th>WORKER</th><th>ROLE / DEPARTMENT</th><th>STATUS</th><th>HIRE DATE</th></tr></thead><tbody>{workers.map((worker) =>
    <tr key={worker.id}><td><span className="governance-person"><i>{worker.full_name.slice(0, 1).toUpperCase()}</i><span><strong>{worker.full_name}</strong><small>{worker.employee_number} · {worker.email || 'No email recorded'}</small></span></span></td><td><strong>{worker.job_title}</strong><small className="governance-subtext">{worker.department}</small></td><td><span className={`governance-status ${worker.status}`}>{worker.status_display}</span></td><td>{new Date(`${worker.hire_date}T00:00:00`).toLocaleDateString()}</td></tr>)}
    {!workers.length && <tr><td colSpan={4} className="governance-table-empty">No team members match this search.</td></tr>}</tbody></table></div>;
}

function AuditTable({ rows, empty }: { rows: AuditRow[]; empty: string }) {
  return <div className="governance-table-scroll"><table className="governance-table governance-audit-table"><thead><tr><th>ACTOR</th><th>ACTION</th><th>TARGET</th><th>TIME</th><th>SOURCE</th></tr></thead><tbody>{rows.map((row) =>
    <tr key={row.id}><td>{row.actor || 'System'}</td><td><strong>{row.action.replace(/_/g, ' ')}</strong></td><td>{row.target}</td><td>{formatDate(row.date)}</td><td><span className="governance-status active">{row.source}</span></td></tr>)}
    {!rows.length && <tr><td colSpan={5} className="governance-table-empty">{empty}</td></tr>}</tbody></table></div>;
}

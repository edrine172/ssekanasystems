import { useEffect, useRef, useState } from 'react';
import {
  Activity, AlertTriangle, ArrowRight, Building2, Check, ChevronRight,
  CircleHelp, Clock3, Database, Download, LoaderCircle, LogOut,
  RefreshCw, Save, Settings2, ShieldCheck, SlidersHorizontal, ToggleLeft,
  Truck, Users, Webhook, X,
} from 'lucide-react';
import { api, getCurrencyDisplay, setCurrencyDisplay, type AccessUser, type ExchangeRatesData, type SettingsAuditEvent, type SystemSettings } from './api';
import { useDataRevision } from './dataSync';
import FileActionMenu from './FileActionMenu';
import { useConfirmation } from './ConfirmDialog';

type DashboardTarget = 'overview' | 'products' | 'inventory' | 'purchases' | 'pos' | 'sales' | 'reports' | 'customers' | 'suppliers' | 'expenses' | 'users';

const modules: Array<{ label: string; target: DashboardTarget; icon: typeof Building2 }> = [
  { label: 'Inventory', target: 'inventory', icon: SlidersHorizontal },
  { label: 'Purchasing', target: 'purchases', icon: Truck },
  { label: 'Point of Sale', target: 'pos', icon: Activity },
  { label: 'Reports', target: 'reports', icon: Database },
  { label: 'Users & Roles', target: 'users', icon: Users },
];

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (checked: boolean) => void; label: string }) {
  return <button className={`settings-toggle ${checked ? 'is-on' : ''}`} type="button" role="switch" aria-checked={checked} aria-label={label} onClick={() => onChange(!checked)}><span/></button>;
}

function AuditValue({ value }: { value: unknown }) {
  if (typeof value === 'boolean') return <span className={`settings-audit-value ${value ? 'enabled' : 'disabled'}`}>{value ? 'Enabled' : 'Disabled'}</span>;
  return <span className="settings-audit-value">{String(value)}</span>;
}

export default function SettingsDashboard({ onNavigate, onSignOut }: { onNavigate: (target: DashboardTarget) => void; onSignOut: () => Promise<void> }) {
  const dataRevision = useDataRevision();
  const { confirm, dialog } = useConfirmation();
  const [settings, setSettings] = useState<SystemSettings | null>(null);
  const [exchangeRates, setExchangeRates] = useState<ExchangeRatesData | null>(null);
  const [rateLoading, setRateLoading] = useState(false);
  const [rateError, setRateError] = useState('');
  const [auditLog, setAuditLog] = useState<SettingsAuditEvent[]>([]);
  const [admin, setAdmin] = useState<AccessUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [settingsDirty, setSettingsDirty] = useState(false);
  const [loginBusy, setLoginBusy] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const settingsFileRef = useRef<HTMLInputElement>(null);

  async function loadExchangeRates() {
    setRateLoading(true);
    setRateError('');
    try {
      const response = await api.exchangeRates();
      setExchangeRates(response);
      setCurrencyDisplay(response.currency, response.rates, response.updated_at);
    } catch (cause) {
      setRateError(cause instanceof Error ? cause.message : 'Live exchange rates could not be loaded.');
    } finally {
      setRateLoading(false);
    }
  }

  async function loadSettings() {
    setLoading(true);
    setError('');
    try {
      const session = await api.accessSession();
      setAdmin(session.user);
      void loadExchangeRates();
      const response = await api.systemSettings();
      setSettings(response.settings);
      setSettingsDirty(false);
      setAuditLog(response.audit_log);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'Settings could not be loaded.';
      if (/authentication credentials|administrator sign-in required/i.test(message)) {
        setAdmin(null);
        setSettings(null);
        setError('');
      } else {
        setError(message);
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!settingsDirty) void loadSettings();
  }, [dataRevision]);

  async function signIn(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoginBusy(true);
    setError('');
    try {
      const session = await api.accessLogin(username, password);
      setAdmin(session.user);
      setPassword('');
      const response = await api.systemSettings();
      setSettings(response.settings);
      setSettingsDirty(false);
      setAuditLog(response.audit_log);
      void loadExchangeRates();
    } catch (cause) {
      setAdmin(null);
      setError(cause instanceof Error ? cause.message : 'Administrator sign-in failed.');
    } finally {
      setLoginBusy(false);
    }
  }

  async function signOut() {
    try {
      await onSignOut();
    } finally {
      setAdmin(null);
      setSettings(null);
      setAuditLog([]);
    }
  }

  function updateSetting<Category extends keyof SystemSettings, Key extends keyof SystemSettings[Category]>(
    category: Category,
    key: Key,
    value: SystemSettings[Category][Key],
  ) {
    setSettings((current) => current ? {
      ...current,
      [category]: { ...current[category], [key]: value },
    } : current);
    setSettingsDirty(true);
  }

  async function saveSettings() {
    if (!settings) return;
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const response = await api.updateSystemSettings(settings);
      setSettings(response.settings);
      setSettingsDirty(false);
      setAuditLog(response.audit_log);
      const currentDisplay = getCurrencyDisplay();
      setCurrencyDisplay(response.settings.organization.currency, exchangeRates?.rates ?? currentDisplay.rates, exchangeRates?.updated_at ?? currentDisplay.updatedAt);
      setNotice('Settings saved and audit trail updated.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Settings could not be saved.');
    } finally {
      setSaving(false);
    }
  }

  async function importSettings(file?: File) {
    if (!file) return;
    setError('');
    setNotice('');
    try {
      const parsed: unknown = JSON.parse(await file.text());
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Choose a valid StockPulse settings JSON file.');
      const candidate = 'settings' in parsed ? (parsed as { settings: unknown }).settings : parsed;
      if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) throw new Error('The JSON file does not contain a settings object.');
      const confirmed = await confirm({
        title: 'Replace current settings?',
        message: 'Import these settings and replace the current values?',
        confirmLabel: 'Import settings',
      });
      if (!confirmed) return;
      setSaving(true);
      const response = await api.updateSystemSettings(candidate as Partial<SystemSettings>);
      setSettings(response.settings);
      setSettingsDirty(false);
      setAuditLog(response.audit_log);
      const currentDisplay = getCurrencyDisplay();
      setCurrencyDisplay(response.settings.organization.currency, exchangeRates?.rates ?? currentDisplay.rates, exchangeRates?.updated_at ?? currentDisplay.updatedAt);
      setNotice('Settings imported and audit trail updated.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Settings could not be imported.');
    } finally {
      setSaving(false);
      if (settingsFileRef.current) settingsFileRef.current.value = '';
    }
  }

  if (loading && !admin) return <section className="overview-state"><LoaderCircle size={17}/>Checking administrator session…</section>;
  if (!admin) return <div className="access-login-wrap"><form className="access-login-panel" onSubmit={(event) => void signIn(event)}><span className="access-login-icon"><ShieldCheck size={22}/></span><span className="access-eyebrow">STOCKPULSE ADMINISTRATION</span><h1>System settings</h1><p>Sign in with a Django superuser account to manage business policies and security controls.</p><label className="catalog-field">Username<input autoComplete="username" required value={username} onChange={(event) => setUsername(event.target.value)}/></label><label className="catalog-field">Password<input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)}/></label>{error && <p className="catalog-form-error">{error}</p>}<button className="catalog-button catalog-button-primary access-login-button" disabled={loginBusy}>{loginBusy ? 'Signing in…' : 'Sign in securely'}</button><small>Administrator accounts are created with Django’s createsuperuser command.</small></form></div>;

  return <div className="settings-page">
    <section className="catalog-heading settings-heading">
      <div><div className="catalog-breadcrumb">System Administration <span>›</span> <b>Global Settings Dashboard</b></div><h1>Settings &amp; Administration Hub</h1><p>Manage business policies, operational defaults, integrations, and security controls.</p></div>
      <div className="catalog-heading-actions">
        <span className="settings-health"><i/> System configuration {error ? 'needs attention' : 'available'}</span>
        <span className="access-session-badge"><i/>Signed in · {admin.username}</span>
        <button className="catalog-button catalog-button-light" onClick={() => void loadSettings()} disabled={loading}><RefreshCw size={14}/>Reload</button>
        <button className="catalog-button catalog-button-light" onClick={() => void signOut()}><LogOut size={14}/>Sign out</button>
        <button className="catalog-button catalog-button-primary" onClick={() => void saveSettings()} disabled={!settings || loading || saving}><Save size={14}/>{saving ? 'Saving…' : 'Save changes'}</button>
      </div>
    </section>

    {error && <div className="settings-message is-error" role="alert"><AlertTriangle size={15}/><span>{error}</span><button onClick={() => void loadSettings()}><RefreshCw size={13}/>Retry</button></div>}
    {notice && <div className="settings-message is-success" role="status"><Check size={15}/>{notice}<button aria-label="Dismiss" onClick={() => setNotice('')}><X size={14}/></button></div>}

    <section className="settings-summary-grid" aria-label="System status">
      <article className="settings-summary"><span className="settings-summary-icon blue"><Building2 size={16}/></span><div><small>BUSINESS INSTANCE</small><strong>{settings?.organization.business_name ?? 'Loading…'}</strong><span>{settings?.organization.default_warehouse ?? 'Configuration loading'}</span></div></article>
      <article className="settings-summary"><span className="settings-summary-icon green"><Webhook size={16}/></span><div><small>CONNECTED SERVICES</small><strong>{settings ? Object.values(settings.integrations).filter(Boolean).length : '—'} / 3 active</strong><span>Accounting, payments, event delivery</span></div></article>
      <article className="settings-summary"><span className="settings-summary-icon violet"><ShieldCheck size={16}/></span><div><small>SECURITY BASELINE</small><strong>{settings?.security.require_two_factor ? '2FA enforced' : 'Standard access'}</strong><span>{settings?.security.session_timeout_minutes ?? '—'} minute session timeout</span></div></article>
      <article className="settings-summary"><span className="settings-summary-icon amber"><Database size={16}/></span><div><small>CONFIGURATION AUDIT</small><strong>{auditLog.length} recent changes</strong><span>{settings?.security.audit_retention_days ?? '—'} day retention</span></div></article>
    </section>

    <div className="settings-layout">
      <div className="settings-main-column">
        <section className="settings-domain-section">
          <div className="settings-section-heading"><div><span className="settings-section-icon"><Settings2 size={15}/></span><h2>Operational configuration domains</h2></div><span>{settings ? '4 modules configured' : 'Loading settings'}</span></div>
          {loading && <div className="settings-loading"><LoaderCircle size={17}/>Loading configuration…</div>}
          {settings && <div className="settings-domain-grid">
            <article className="settings-domain-card">
              <header><span className="settings-card-icon"><Building2 size={16}/></span><span className="settings-card-status"><i/> Business profile</span></header>
              <h3>Organization &amp; instance</h3><p>Set the legal identity, operating currency, time zone, and primary warehouse used across the suite.</p>
              <label className="settings-field">Business name<input value={settings.organization.business_name} onChange={(event) => updateSetting('organization', 'business_name', event.target.value)}/></label>
              <div className="settings-field-row"><label className="settings-field">Tax ID<input value={settings.organization.tax_id} onChange={(event) => updateSetting('organization', 'tax_id', event.target.value)} placeholder="Optional"/></label><label className="settings-field">Display currency<select value={settings.organization.currency} disabled={rateLoading || !exchangeRates} onChange={(event) => updateSetting('organization', 'currency', event.target.value)}>{!exchangeRates?.rates[settings.organization.currency] && <option value={settings.organization.currency}>{settings.organization.currency} · no live rate</option>}{Object.keys(exchangeRates?.rates ?? {}).sort().map((code) => <option key={code} value={code}>{code}</option>)}</select></label></div>
              <p className="settings-currency-note">{rateError ? `Exchange rates unavailable: ${rateError} Display remains in UGX until rates load.` : rateLoading ? 'Loading live exchange rates…' : exchangeRates ? `Save changes to apply the display currency. Amounts stay stored in UGX and are converted for display. Rates last updated ${exchangeRates.updated_at}.` : 'Load live exchange rates to choose a display currency.'}</p>
              <div className="settings-field-row"><label className="settings-field">Time zone<select value={settings.organization.timezone} onChange={(event) => updateSetting('organization', 'timezone', event.target.value)}><option>Africa/Kampala</option><option>Africa/Nairobi</option><option>UTC</option><option>Europe/London</option></select></label><label className="settings-field">Default warehouse<input value={settings.organization.default_warehouse} onChange={(event) => updateSetting('organization', 'default_warehouse', event.target.value)}/></label></div>
            </article>

            <article className="settings-domain-card">
              <header><span className="settings-card-icon"><SlidersHorizontal size={16}/></span><span className="settings-card-status"><i/> Inventory rules</span></header>
              <h3>Inventory &amp; stock rules</h3><p>Control low-stock defaults and the guardrails used by purchasing and point-of-sale workflows.</p>
              <label className="settings-field">Default reorder threshold<input type="number" min="1" value={settings.operations.reorder_threshold} onChange={(event) => updateSetting('operations', 'reorder_threshold', Number(event.target.value))}/></label>
              <label className="settings-choice"><span><strong>Allow negative stock</strong><small>Permit sales when available quantity is zero.</small></span><Toggle label="Allow negative stock" checked={settings.operations.allow_negative_stock} onChange={(value) => updateSetting('operations', 'allow_negative_stock', value)}/></label>
              <label className="settings-choice"><span><strong>Auto-create purchase drafts</strong><small>Prepare a draft when stock reaches its threshold.</small></span><Toggle label="Auto-create purchase drafts" checked={settings.operations.auto_purchase_drafts} onChange={(value) => updateSetting('operations', 'auto_purchase_drafts', value)}/></label>
              <label className="settings-field">Default payment terms<select value={settings.operations.default_payment_terms} onChange={(event) => updateSetting('operations', 'default_payment_terms', event.target.value)}><option>Due on receipt</option><option>Net 15</option><option>Net 30</option><option>Net 60</option></select></label>
            </article>

            <article className="settings-domain-card">
              <header><span className="settings-card-icon"><ShieldCheck size={16}/></span><span className="settings-card-status"><i/> Security policies</span></header>
              <h3>Access &amp; audit controls</h3><p>Configure session handling, stronger sign-in requirements, and how long configuration events are retained.</p>
              <label className="settings-choice"><span><strong>Require two-factor authentication</strong><small>Require an additional verification step at sign-in.</small></span><Toggle label="Require two-factor authentication" checked={settings.security.require_two_factor} onChange={(value) => updateSetting('security', 'require_two_factor', value)}/></label>
              <div className="settings-field-row"><label className="settings-field">Session timeout (minutes)<input type="number" min="1" max="1440" value={settings.security.session_timeout_minutes} onChange={(event) => updateSetting('security', 'session_timeout_minutes', Number(event.target.value))}/></label><label className="settings-field">Audit retention (days)<input type="number" min="1" value={settings.security.audit_retention_days} onChange={(event) => updateSetting('security', 'audit_retention_days', Number(event.target.value))}/></label></div>
              <div className="settings-info-note"><CircleHelp size={14}/> Changes are recorded with their previous and new values.</div>
            </article>

            <article className="settings-domain-card settings-integrations-card">
              <header><span className="settings-card-icon"><Webhook size={16}/></span><span className="settings-card-status"><i/> {Object.values(settings.integrations).filter(Boolean).length} services active</span></header>
              <h3>External connectors</h3><p>Choose which connected services can exchange data with this StockPulse instance.</p>
              <label className="settings-choice"><span><strong>QuickBooks</strong><small>Accounting sync</small></span><Toggle label="Enable QuickBooks" checked={settings.integrations.quickbooks_enabled} onChange={(value) => updateSetting('integrations', 'quickbooks_enabled', value)}/></label>
              <label className="settings-choice"><span><strong>Stripe</strong><small>Payment processing</small></span><Toggle label="Enable Stripe" checked={settings.integrations.stripe_enabled} onChange={(value) => updateSetting('integrations', 'stripe_enabled', value)}/></label>
              <label className="settings-choice"><span><strong>Outbound webhooks</strong><small>Event notifications for connected apps</small></span><Toggle label="Enable outbound webhooks" checked={settings.integrations.webhooks_enabled} onChange={(value) => updateSetting('integrations', 'webhooks_enabled', value)}/></label>
              <div className="settings-info-note"><Check size={14}/> Connector credentials are managed by the deployment administrator.</div>
            </article>
          </div>}
        </section>

        <section className="settings-audit-panel">
          <div className="settings-panel-heading"><div><span className="settings-card-icon"><Activity size={15}/></span><div><h2>Recent configuration &amp; security log</h2><p>Immutable record of administrator setting changes.</p></div></div><span className="settings-live-badge"><i/> Live audit</span></div>
          {auditLog.length ? <div className="settings-audit-table-wrap"><table className="settings-audit-table"><thead><tr><th>Timestamp</th><th>Changed by</th><th>Setting</th><th>Previous</th><th>New value</th></tr></thead><tbody>{auditLog.slice(0, 8).map((event) => <tr key={event.id}><td><Clock3 size={12}/>{new Date(event.created_at).toLocaleString()}</td><td>{event.actor_name}</td><td><strong>{event.target_id.replace(/_/g, ' ')}</strong></td><td><AuditValue value={event.details.previous}/></td><td><AuditValue value={event.details.value}/></td></tr>)}</tbody></table></div> : <div className="settings-audit-empty"><Activity size={17}/><span>No configuration changes have been recorded yet.</span></div>}
          <div className="settings-audit-footer"><span>Showing the latest {Math.min(auditLog.length, 8)} of {auditLog.length} setting changes</span><span>Audit retention: {settings?.security.audit_retention_days ?? '—'} days</span></div>
        </section>
      </div>

      <aside className="settings-side-column">
        <section className="settings-side-panel">
          <div className="settings-side-heading"><span><ShieldCheck size={15}/></span><h2>Governance &amp; guardrails</h2><small>Active</small></div>
          <div className="settings-guardrail"><span><strong>Negative stock</strong><small>{settings?.operations.allow_negative_stock ? 'Sales may exceed available quantity.' : 'Sales are blocked when stock is unavailable.'}</small></span><i className={settings?.operations.allow_negative_stock ? 'warn' : 'secure'}>{settings?.operations.allow_negative_stock ? 'Review' : 'On'}</i></div>
          <div className="settings-guardrail"><span><strong>Two-factor sign-in</strong><small>{settings?.security.require_two_factor ? 'Additional verification is required.' : 'Standard administrator sign-in.'}</small></span><i className={settings?.security.require_two_factor ? 'secure' : 'neutral'}>{settings?.security.require_two_factor ? 'On' : 'Off'}</i></div>
          <div className="settings-guardrail"><span><strong>Audit history</strong><small>Configuration changes are recorded automatically.</small></span><i className="secure">Live</i></div>
        </section>

        <section className="settings-side-panel">
          <div className="settings-side-heading"><span><ToggleLeft size={15}/></span><h2>Integrated infrastructure</h2><button title="Reload integration states" onClick={() => void loadSettings()}><RefreshCw size={13}/></button></div>
          {settings && ([
            ['QuickBooks Enterprise', 'Accounting sync', settings.integrations.quickbooks_enabled],
            ['Stripe POS & Payments', 'Payment processing', settings.integrations.stripe_enabled],
            ['Webhook delivery', 'External event stream', settings.integrations.webhooks_enabled],
          ] as const).map(([name, detail, enabled]) => <div className="settings-service-row" key={name}><span className="settings-service-icon"><Webhook size={14}/></span><span><strong>{name}</strong><small>{detail}</small></span><i className={enabled ? 'connected' : 'disconnected'}>{enabled ? 'On' : 'Off'}</i></div>)}
        </section>

        <section className="settings-side-panel settings-navigation-panel">
          <div className="settings-side-heading"><span><ArrowRight size={15}/></span><h2>Operational dashboards</h2></div>
          <p>Jump directly to a connected workspace.</p>
          {modules.map(({ label, target, icon: Icon }) => <button className="settings-module-link" key={target} onClick={() => onNavigate(target)}><Icon size={14}/><span>{label}</span><ChevronRight size={14}/></button>)}
        </section>

        <section className="settings-backup-panel"><div><Download size={15}/><strong>Configuration backup</strong></div><p>Import or export the current settings as JSON.</p><input ref={settingsFileRef} className="catalog-hidden" type="file" accept=".json,application/json" onChange={(event) => void importSettings(event.target.files?.[0])}/><FileActionMenu label="File options" direction="files" options={[{ label: 'Import settings JSON', direction: 'import', onSelect: () => settingsFileRef.current?.click(), disabled: saving }, { label: 'Export settings JSON', direction: 'export', onSelect: () => {
          if (!settings) return;
          const link = document.createElement('a');
          link.href = URL.createObjectURL(new Blob([JSON.stringify(settings, null, 2)], { type: 'application/json' }));
          link.download = 'stockpulse-settings.json';
          link.click();
          URL.revokeObjectURL(link.href);
        }, disabled: !settings || saving }]}/></section>
      </aside>
    </div>
    {dialog}
  </div>;
}
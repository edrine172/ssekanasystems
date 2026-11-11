import { useEffect, useMemo, useState } from 'react';
import { Activity, Check, KeyRound, LockKeyhole, LogOut, Plus, RefreshCw, Shield, ShieldCheck, ToggleLeft, ToggleRight, UserPlus, Users, X } from 'lucide-react';
import { api, type AccessDashboardData, type AccessGroup, type AccessPermission, type AccessUser } from './api';
import { useDataRevision } from './dataSync';

type AccessTab = 'roles' | 'users' | 'audit';
const actions = ['view', 'add', 'change', 'delete'];
const actionLabels: Record<string, string> = { view: 'View', add: 'Create', change: 'Edit', delete: 'Delete' };
const moduleLabels: Record<string, string> = {
  category: 'Categories', customer: 'Customers & CRM', expense: 'Expenses & Disbursements', expensebudget: 'Expense Budgets',
  product: 'Products & Catalog', purchase: 'Purchases & Inbound POs', purchaseitem: 'Purchase Line Items', sale: 'Sales & Customer Invoicing',
  saleitem: 'Sales Line Items', stockmovement: 'Inventory & Stock Adjustments', supplier: 'Suppliers & Vendor Management',
  supplierinspection: 'Supplier Quality Inspections', supplierledgerentry: 'Supplier Payables', customerledgerentry: 'Customer Ledger',
};
const moduleOrder = ['category', 'product', 'stockmovement', 'purchase', 'purchaseitem', 'sale', 'saleitem', 'customer', 'customerledgerentry', 'supplier', 'supplierinspection', 'supplierledgerentry', 'expense', 'expensebudget'];

function moduleLabel(model: string) { return moduleLabels[model] ?? model.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/^./, (value) => value.toUpperCase()); }
function formatDate(value: string | null) { return value ? new Date(value).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : 'Never'; }

function LoginPanel({ onLogin }: { onLogin: (username: string, password: string) => Promise<void> }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try { await onLogin(username, password); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Administrator sign-in failed.'); }
    finally { setBusy(false); }
  }
  return <div className="access-login-wrap"><form className="access-login-panel" onSubmit={submit}><span className="access-login-icon"><ShieldCheck size={22}/></span><span className="access-eyebrow">STOCKPULSE ADMINISTRATION</span><h1>Users &amp; Access</h1><p>Sign in with a Django superuser account to manage users and roles.</p><label className="catalog-field">Username<input autoComplete="username" required value={username} onChange={(event) => setUsername(event.target.value)}/></label><label className="catalog-field">Password<input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)}/></label>{error && <p className="catalog-form-error">{error}</p>}<button className="catalog-button catalog-button-primary access-login-button" disabled={busy}>{busy ? 'Signing in…' : 'Sign in securely'}</button><small>Administrator accounts are created with Django’s createsuperuser command.</small></form></div>;
}

function UserForm({ groups, user, canCreateSuperusers, onClose, onSaved }: { groups: AccessGroup[]; user?: AccessUser | null; canCreateSuperusers: boolean; onClose: () => void; onSaved: (user: AccessUser) => Promise<void> }) {
  const [draft, setDraft] = useState(() => ({
    username: user?.username ?? '',
    email: user?.email ?? '',
    first_name: user?.first_name ?? '',
    last_name: user?.last_name ?? '',
    password: '',
    is_staff: user?.is_staff ?? true,
    is_superuser: false,
    groups: user?.groups.map((group) => typeof group === 'number' ? group : group.id) ?? [] as number[],
  }));
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  function toggleGroup(id: number) { setDraft((current) => ({ ...current, groups: current.groups.includes(id) ? current.groups.filter((groupId) => groupId !== id) : [...current.groups, id] })); }
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError('');
    try {
      const saved = user
        ? await api.updateAccessUser(user.id, {
          username: draft.username,
          email: draft.email,
          first_name: draft.first_name,
          last_name: draft.last_name,
          is_staff: draft.is_staff,
          groups: draft.groups,
          ...(draft.password ? { password: draft.password } : {}),
        })
        : await api.createAccessUser({
          ...draft,
          is_active: true,
          is_staff: draft.is_staff || draft.is_superuser,
          groups: draft.is_superuser ? [] : draft.groups,
        });
      await onSaved(saved);
    }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not invite this user.'); }
    finally { setSaving(false); }
  }
  return <div className="catalog-overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <form className="catalog-modal access-user-modal" onSubmit={submit}>
      <div className="catalog-modal-heading">
        <div><span className="catalog-eyebrow">TEAM ACCESS</span><h2>{user ? 'Edit user access' : 'Invite new user'}</h2><p>{user ? 'Update credentials, dashboard access, and assigned roles.' : 'Create an account and choose its dashboard access and roles.'}</p></div>
        <button className="catalog-icon-button" type="button" onClick={onClose} aria-label="Close"><X size={18}/></button>
      </div>
      <div className="catalog-form-row">
        <label className="catalog-field">First name<input required maxLength={150} value={draft.first_name} onChange={(event) => setDraft((current) => ({ ...current, first_name: event.target.value }))}/></label>
        <label className="catalog-field">Last name<input required maxLength={150} value={draft.last_name} onChange={(event) => setDraft((current) => ({ ...current, last_name: event.target.value }))}/></label>
      </div>
      <div className="catalog-form-row">
        <label className="catalog-field">Username<input required autoComplete="off" maxLength={150} value={draft.username} onChange={(event) => setDraft((current) => ({ ...current, username: event.target.value }))}/></label>
        <label className="catalog-field">Work email<input type="email" required value={draft.email} onChange={(event) => setDraft((current) => ({ ...current, email: event.target.value }))}/></label>
      </div>
      <label className="catalog-field">{user ? 'Reset password (leave blank to keep current)' : 'Temporary password'}
        <input type="password" required={!user} minLength={8} autoComplete="new-password" value={draft.password} onChange={(event) => setDraft((current) => ({ ...current, password: event.target.value }))}/>
      </label>
      <fieldset className="access-group-options">
        <legend>Account access</legend>
        <label><input type="checkbox" checked={draft.is_staff || draft.is_superuser} disabled={draft.is_superuser} onChange={(event) => setDraft((current) => ({ ...current, is_staff: event.target.checked }))}/>Allow dashboard sign-in</label>
        <small>{draft.is_superuser ? 'Superadmins always have dashboard access.' : 'Dashboard access is also limited by the permissions granted to the assigned roles.'}</small>
      </fieldset>
      {canCreateSuperusers && !user && <fieldset className="access-group-options">
        <legend>Administrator access</legend>
        <label><input type="checkbox" checked={draft.is_superuser} onChange={(event) => setDraft((current) => ({ ...current, is_superuser: event.target.checked, is_staff: event.target.checked || current.is_staff, groups: event.target.checked ? [] : current.groups }))}/>Create as superadmin</label>
        <small>Superadmins have unrestricted access to all system data, users, and settings.</small>
      </fieldset>}
      {!draft.is_superuser && <fieldset className="access-group-options">
        <legend>Assign roles</legend>
        {groups.map((group) => <label key={group.id}><input type="checkbox" checked={draft.groups.includes(group.id)} onChange={() => toggleGroup(group.id)}/>{group.name}</label>)}
        {!groups.length && <small>Create a role before assigning groups.</small>}
      </fieldset>}
      {error && <p className="catalog-form-error">{error}</p>}
      <div className="catalog-modal-actions">
        <button type="button" className="catalog-button catalog-button-light" onClick={onClose}>Cancel</button>
        <button className="catalog-button catalog-button-primary" disabled={saving}>{saving ? 'Saving…' : user ? 'Save user' : 'Create user'}</button>
      </div>
    </form>
  </div>;
}

function RoleForm({ onClose, onSaved }: { onClose: () => void; onSaved: (group: AccessGroup) => Promise<void> }) {
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError('');
    try { await onSaved(await api.createAccessGroup(name.trim())); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not create role.'); }
    finally { setSaving(false); }
  }
  return <div className="catalog-overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><form className="catalog-modal access-role-modal" onSubmit={submit}><div className="catalog-modal-heading"><div><span className="catalog-eyebrow">ROLE MANAGEMENT</span><h2>Create role</h2><p>Start with an empty permission set, then configure access.</p></div><button className="catalog-icon-button" type="button" onClick={onClose} aria-label="Close"><X size={18}/></button></div><label className="catalog-field">Role name<input required maxLength={150} value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Inventory Coordinator"/></label>{error && <p className="catalog-form-error">{error}</p>}<div className="catalog-modal-actions"><button type="button" className="catalog-button catalog-button-light" onClick={onClose}>Cancel</button><button className="catalog-button catalog-button-primary" disabled={saving}>{saving ? 'Creating…' : 'Create role'}</button></div></form></div>;
}

export default function UsersDashboard({ onSignOut }: { onSignOut: () => Promise<void> }) {
  const dataRevision = useDataRevision();
  const [admin, setAdmin] = useState<AccessUser | null>(null);
  const [dashboard, setDashboard] = useState<AccessDashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<AccessTab>('roles');
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [permissionDraft, setPermissionDraft] = useState<number[]>([]);
  const [dirtyPermissions, setDirtyPermissions] = useState(false);
  const [search, setSearch] = useState('');
  const [showUserForm, setShowUserForm] = useState(false);
  const [editingUser, setEditingUser] = useState<AccessUser | null>(null);
  const [showRoleForm, setShowRoleForm] = useState(false);
  const [notice, setNotice] = useState('');

  async function loadDashboard() {
    setLoading(true); setError('');
    try {
      const { user } = await api.accessSession();
      setAdmin(user);
      const data = await api.accessDashboard();
      setDashboard(data);
      setSelectedGroupId((current) => current && data.groups.some((group) => group.id === current) ? current : data.groups[0]?.id ?? null);
    } catch (cause) {
      setAdmin(null);
      setDashboard(null);
      const message = cause instanceof Error ? cause.message : 'Could not load access controls.';
      setError(/authentication credentials|administrator sign-in required/i.test(message) ? '' : message);
    } finally { setLoading(false); }
  }

  useEffect(() => {
    if (!dirtyPermissions) void loadDashboard();
  }, [dataRevision]);
  const selectedGroup = dashboard?.groups.find((group) => group.id === selectedGroupId) ?? null;
  useEffect(() => {
    setPermissionDraft(selectedGroup?.permission_ids ?? []);
    setDirtyPermissions(false);
  }, [selectedGroupId, dashboard]);

  const filteredUsers = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (dashboard?.users ?? []).filter((user) => `${user.username} ${user.email} ${user.first_name} ${user.last_name} ${user.group_names?.join(' ') ?? ''}`.toLowerCase().includes(term));
  }, [dashboard, search]);
  const groupedPermissions = useMemo(() => {
    const grouped = new Map<string, AccessPermission[]>();
    for (const permission of dashboard?.permissions ?? []) grouped.set(permission.model, [...(grouped.get(permission.model) ?? []), permission]);
    return [...grouped.entries()].sort((a, b) => {
      const aIndex = moduleOrder.indexOf(a[0]); const bIndex = moduleOrder.indexOf(b[0]);
      return (aIndex < 0 ? 999 : aIndex) - (bIndex < 0 ? 999 : bIndex);
    });
  }, [dashboard]);

  async function signIn(username: string, password: string) {
    const result = await api.accessLogin(username, password);
    setAdmin(result.user);
    setDashboard(await api.accessDashboard());
  }

  async function savePermissions() {
    if (!selectedGroup) return;
    setError('');
    try {
      await api.setGroupPermissions(selectedGroup.id, permissionDraft);
      await loadDashboard();
      setNotice(`${selectedGroup.name} permissions saved.`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not save permissions.'); }
  }

  async function toggleUser(user: AccessUser) {
    setError('');
    try {
      await api.updateAccessUser(user.id, { is_active: !user.is_active });
      await loadDashboard();
      setNotice(`${user.username} ${user.is_active ? 'disabled' : 'activated'}.`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not update this account.'); }
  }

  async function revokeSessions(user: AccessUser) {
    setError('');
    try {
      const result = await api.forceLogoutAccessUser(user.id);
      await loadDashboard();
      setNotice(`${result.revoked_sessions} active session${result.revoked_sessions === 1 ? '' : 's'} revoked for ${user.username}.`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not revoke user sessions.'); }
  }

  async function createRole(group: AccessGroup) { setShowRoleForm(false); await loadDashboard(); setSelectedGroupId(group.id); setTab('roles'); setNotice(`${group.name} role created.`); }
  async function signOut() { await onSignOut(); setAdmin(null); setDashboard(null); setNotice('Administrator signed out.'); }

  if (loading && !admin) return <section className="overview-state">Checking administrator session…</section>;
  if (!admin) return <><LoginPanel onLogin={signIn}/>{error && <div className="access-login-error">{error}</div>}</>;
  if (!dashboard) return <section className="overview-state overview-error"><strong>Could not load access governance</strong><span>{error}</span><button className="catalog-button catalog-button-light" onClick={() => void loadDashboard()}><RefreshCw size={14}/>Retry</button></section>;

  function hasPermission(permission: AccessPermission) { return permissionDraft.includes(permission.id); }
  function togglePermission(permission: AccessPermission) {
    setPermissionDraft((current) => current.includes(permission.id) ? current.filter((id) => id !== permission.id) : [...current, permission.id]);
    setDirtyPermissions(true);
  }

  return <>
    <section className="catalog-heading access-heading"><div><div className="catalog-breadcrumb">Settings &amp; Administration <span>›</span> <b>Access Control &amp; Security</b></div><h1>Users &amp; Access Governance</h1><p>Manage team credentials, Django groups, and model-level permissions.</p></div><div className="catalog-heading-actions"><span className="access-session-badge"><i/>Signed in · {admin.username}</span><button className="catalog-button catalog-button-light" onClick={() => void loadDashboard()}><RefreshCw size={13}/>Refresh</button><button className="catalog-button catalog-button-light" onClick={() => void signOut()}><LogOut size={13}/>Sign out</button></div></section>
    <section className="overview-metrics access-metrics"><article><div><span>ACTIVE ACCOUNTS</span><Users size={14}/></div><strong>{dashboard.active_users}</strong><small>{dashboard.staff_users} staff accounts · {dashboard.total_users} total</small></article><article><div><span>SYSTEM ROLES</span><Shield size={14}/></div><strong>{dashboard.role_count}</strong><small>{dashboard.permission_count} inventory permissions available</small></article><article className="security"><div><span>PERMISSION COVERAGE</span><ShieldCheck size={14}/></div><strong>{dashboard.groups.filter((group) => group.permission_ids.length > 0).length} / {dashboard.role_count}</strong><small>Roles with explicit access rules</small></article><article className="locked"><div><span>DISABLED ACCOUNTS</span><LockKeyhole size={14}/></div><strong>{dashboard.disabled_users}</strong><small>Account access disabled</small></article></section>
    <div className="access-tabs" role="tablist" aria-label="Access administration"><button className={tab === 'roles' ? 'active' : ''} onClick={() => setTab('roles')}><Shield size={13}/>Role permissions <span>{dashboard.role_count}</span></button><button className={tab === 'users' ? 'active' : ''} onClick={() => setTab('users')}><Users size={13}/>User directory <span>{dashboard.total_users}</span></button><button className={tab === 'audit' ? 'active' : ''} onClick={() => setTab('audit')}><Activity size={13}/>Security audit &amp; session trails <span>{dashboard.audit_log.length}</span></button></div>
    {error && <div className="access-inline-error">{error}</div>}
    {notice && <div className="catalog-toast"><Check size={15}/>{notice}<button onClick={() => setNotice('')} aria-label="Dismiss"><X size={14}/></button></div>}

    {tab === 'roles' && <>
      <div className="access-role-toolbar"><div className="access-role-selector">{dashboard.groups.map((group) => <button key={group.id} className={selectedGroupId === group.id ? 'active' : ''} onClick={() => setSelectedGroupId(group.id)}><Shield size={13}/>{group.name}<span>{group.member_count}</span></button>)}</div><button className="catalog-button catalog-button-light" onClick={() => setShowRoleForm(true)}><Plus size={13}/>Create role</button></div>
      {selectedGroup && <><section className="overview-panel access-role-summary"><div><span>SELECTED ROLE</span><h2>{selectedGroup.name}</h2><p>{selectedGroup.member_count} assigned users · {selectedGroup.permission_ids.length} granted permissions</p></div><span className="access-role-version">Django Group</span></section><section className="catalog-table-panel access-permission-panel"><div className="access-permission-heading"><div><h2>Module permissions &amp; access vectors</h2><span>{groupedPermissions.length} Django content types</span></div><button className="catalog-button catalog-button-primary" disabled={!dirtyPermissions} onClick={() => void savePermissions()}><Check size={13}/>Save permission changes</button></div><div className="catalog-table-scroll"><table className="catalog-table access-permission-table"><thead><tr><th>MODULE / DOMAIN</th>{actions.map((action) => <th key={action}>{actionLabels[action]}</th>)}<th>PERMISSIONS</th></tr></thead><tbody>{groupedPermissions.map(([model, permissions]) => <tr key={model}><td><strong>{moduleLabel(model)}</strong><small>inventory.{model}</small></td>{actions.map((action) => { const permission = permissions.find((item) => item.action === action); return <td key={action}>{permission ? <input type="checkbox" aria-label={`${actionLabels[action]} ${moduleLabel(model)}`} checked={hasPermission(permission)} onChange={() => togglePermission(permission)}/> : <span className="access-not-applicable">—</span>}</td>; })}<td><span className="access-permission-count">{permissions.filter((permission) => permissionDraft.includes(permission.id)).length} / {permissions.length} granted</span></td></tr>)}</tbody></table></div><footer className="access-permission-footer"><span>Permission changes apply immediately to Django group membership.</span><button className="catalog-clear" disabled={!dirtyPermissions} onClick={() => { setPermissionDraft(selectedGroup.permission_ids); setDirtyPermissions(false); void loadDashboard(); }}>Discard changes</button></footer></section></>}
    </>}

    {tab === 'users' && <><div className="access-user-toolbar"><label className="catalog-search"><Users size={14}/><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search username, name, email, or role"/></label><button className="catalog-button catalog-button-primary" onClick={() => setShowUserForm(true)}><UserPlus size={14}/>Invite user</button></div><section className="catalog-table-panel access-users-panel"><div className="catalog-table-scroll"><table className="catalog-table access-users-table"><thead><tr><th>USER</th><th>ROLES / GROUPS</th><th>ACCOUNT TYPE</th><th>LAST LOGIN</th><th>STATUS</th><th>ACTION</th></tr></thead><tbody>{filteredUsers.map((user) => <tr key={user.id}><td><span className="access-user-name"><i>{(user.first_name || user.username).slice(0, 1).toUpperCase()}</i><span><strong>{[user.first_name, user.last_name].filter(Boolean).join(' ') || user.username}</strong><small>{user.email || user.username}</small></span></span></td><td><div className="access-user-groups">{(user.group_names ?? []).length ? user.group_names?.map((name) => <span key={name}>{name}</span>) : <span className="no-role">No role assigned</span>}</div></td><td>{user.is_superuser ? 'Superuser' : user.is_staff ? 'Staff' : 'Standard'}</td><td>{formatDate(user.last_login)}</td><td><span className={`access-user-status ${user.is_active ? 'active' : ''}`}>{user.is_active ? 'Active' : 'Disabled'}</span></td><td><div className="access-user-actions"><button className="catalog-button catalog-button-light access-toggle-button" disabled={user.is_superuser} onClick={() => setEditingUser(user)}>Edit roles</button><button className="catalog-button catalog-button-light access-toggle-button" disabled={user.is_superuser} onClick={() => void toggleUser(user)}>{user.is_active ? <><ToggleRight size={14}/>Disable</> : <><ToggleLeft size={14}/>Activate</>}</button><button className="catalog-button catalog-button-light access-toggle-button" disabled={user.is_superuser || user.id === admin.id} onClick={() => void revokeSessions(user)}>Revoke sessions</button></div></td></tr>)}{!filteredUsers.length && <tr><td colSpan={6} className="catalog-state">No users match this search.</td></tr>}</tbody></table></div></section></>}

    {tab === 'audit' && <section className="overview-panel access-audit-panel"><div className="overview-panel-heading"><div><span>IMMUTABLE SECURITY LOG</span><h2>Role governance trail</h2></div><span className="access-audit-live"><i/>Live audit log</span></div>{dashboard.audit_log.map((event) => <article className="access-audit-entry" key={event.id}><span className="access-audit-icon"><KeyRound size={13}/></span><div><strong>{event.action.replace(/[._]/g, ' ')}</strong><small>{event.actor_name} · {event.target_type} {event.target_id}{Object.keys(event.details).length ? ` · ${JSON.stringify(event.details)}` : ''}</small></div><time>{formatDate(event.created_at)}</time></article>)}{!dashboard.audit_log.length && <p className="overview-empty">User, group, and permission changes will be recorded here.</p>}</section>}

    {(showUserForm || editingUser) && <UserForm user={editingUser} groups={dashboard.groups} canCreateSuperusers={admin.is_superuser} onClose={() => { setShowUserForm(false); setEditingUser(null); }} onSaved={async (user) => { setShowUserForm(false); setEditingUser(null); await loadDashboard(); setTab('users'); setNotice(`${user.username} access updated.`); }}/ >}
    {showRoleForm && <RoleForm onClose={() => setShowRoleForm(false)} onSaved={createRole}/>}
  </>;
}
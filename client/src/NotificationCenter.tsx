import { useEffect, useState } from 'react';
import { AlertTriangle, Bell, CheckCheck, Clock3, Package, RefreshCw, Truck, WalletCards, X } from 'lucide-react';
import { api, type AppNotification, type NotificationCategory, type NotificationDashboard } from './api';
import { useDataRevision } from './dataSync';

const categoryLabels: Record<NotificationCategory, string> = {
  stock: 'Stock alerts',
  procurement: 'Procurement & POs',
  billing: 'Billing & sales',
  operations: 'Operations',
};

const categoryHeadings: Record<NotificationCategory, string> = {
  stock: 'STOCK DEPLETION & SAFETY THRESHOLDS',
  procurement: 'PROCUREMENT & INBOUND MANIFESTS',
  billing: 'BILLING & CUSTOMER ACCOUNTS',
  operations: 'OPERATIONS & APPROVALS',
};

const categoryIcons = {
  stock: Package,
  procurement: Truck,
  billing: WalletCards,
  operations: AlertTriangle,
};

const alertCategories: NotificationCategory[] = ['stock', 'procurement', 'billing', 'operations'];
const categories: Array<'all' | NotificationCategory> = ['all', ...alertCategories];

function relativeTime(value: string) {
  const elapsed = Math.max(0, Date.now() - new Date(value).getTime());
  const minutes = Math.floor(elapsed / 60_000);
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes} min${minutes === 1 ? '' : 's'} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? '' : 's'} ago`;
}

export default function NotificationCenter({ onNavigate }: { onNavigate: (view: NotificationDashboard) => void }) {
  const dataRevision = useDataRevision();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState<'all' | NotificationCategory>('all');
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const unreadCount = notifications.filter((notification) => !notification.is_read).length;

  useEffect(() => {
    let mounted = true;
    const loadNotifications = async () => {
      try {
        const result = await api.notifications();
        if (mounted) { setNotifications(result); setError(''); }
      } catch (cause) {
        if (mounted) setError(cause instanceof Error ? cause.message : 'Notifications could not be loaded.');
      } finally {
        if (mounted) setLoading(false);
      }
    };
    void loadNotifications();
    const interval = window.setInterval(() => { void loadNotifications(); }, 45_000);
    return () => { mounted = false; window.clearInterval(interval); };
  }, [dataRevision]);

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false); };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [open]);

  async function markRead(notification: AppNotification) {
    if (notification.is_read) return;
    try {
      const updated = await api.markNotificationRead(notification.id);
      setNotifications((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not update this notification.');
    }
  }

  async function markAllRead() {
    try {
      await api.markAllNotificationsRead();
      setNotifications((current) => current.map((item) => ({ ...item, is_read: true })));
      setError('');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not update notifications.');
    }
  }

  async function dismiss(notification: AppNotification) {
    try {
      await api.dismissNotification(notification.id);
      setNotifications((current) => current.filter((item) => item.id !== notification.id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not dismiss this notification.');
    }
  }

  const filtered = notifications.filter((notification) => filter === 'all' || notification.category === filter);
  const visibleCategories: NotificationCategory[] = filter === 'all' ? alertCategories : [filter];

  return <>
    <button className="catalog-icon-button catalog-bell notification-bell" aria-label={`Notifications${unreadCount ? `, ${unreadCount} unread` : ''}`} aria-expanded={open} onClick={() => setOpen(true)}>
      <Bell size={17}/>{unreadCount > 0 && <span className="notification-badge">{unreadCount > 9 ? '9+' : unreadCount}</span>}
    </button>
    {open && <div className="notification-overlay">
      <button className="notification-scrim" aria-label="Close notifications" onClick={() => setOpen(false)}/>
      <aside className="notification-panel" role="dialog" aria-modal="true" aria-labelledby="notification-title">
        <header className="notification-header">
          <div className="notification-heading-icon"><Bell size={17}/></div>
          <div className="notification-heading-copy"><h2 id="notification-title">Notification Center</h2><p>Live operational alerts and updates</p></div>
          <div className="notification-unread-count"><strong>{unreadCount}</strong><span>Unread</span></div>
          <button className="notification-tool" title="Mark all as read" aria-label="Mark all notifications as read" onClick={() => void markAllRead()} disabled={unreadCount === 0}><CheckCheck size={16}/></button>
          <button className="notification-tool" title="Close" aria-label="Close notifications" onClick={() => setOpen(false)}><X size={17}/></button>
        </header>
        <nav className="notification-filters" aria-label="Filter notifications">
          {categories.map((category) => {
            const count = category === 'all' ? notifications.length : notifications.filter((item) => item.category === category).length;
            return <button key={category} className={filter === category ? 'active' : ''} onClick={() => setFilter(category)}>{category === 'all' ? 'All' : categoryLabels[category]} <span>{count}</span></button>;
          })}
        </nav>
        <div className="notification-list">
          {error && <div className="notification-error" role="status">{error}</div>}
          {loading && notifications.length === 0 && <p className="notification-empty">Loading notifications…</p>}
          {!loading && filtered.length === 0 && <div className="notification-empty"><Bell size={20}/><strong>You're all caught up</strong><span>No {filter === 'all' ? '' : `${categoryLabels[filter].toLowerCase()} `}notifications right now.</span></div>}
          {visibleCategories.map((category) => {
            const group = filtered.filter((notification) => notification.category === category);
            if (!group.length) return null;
            const Icon = categoryIcons[category];
            return <section className="notification-group" key={category}>
              <div className={`notification-group-heading ${category}`}><strong><Icon size={12}/>{categoryHeadings[category]}</strong><span>{group.filter((item) => !item.is_read).length} unread</span></div>
              {group.map((notification) => <article className={`notification-card ${notification.severity} ${notification.is_read ? 'read' : ''}`} key={notification.id}>
                <div className={`notification-card-icon ${notification.severity}`}><Icon size={16}/></div>
                <div className="notification-card-content">
                  <div className="notification-card-meta"><span className={`notification-severity ${notification.severity}`}>{notification.severity === 'critical' ? 'Critical' : notification.severity === 'warning' ? 'Attention' : categoryLabels[category]}</span>{notification.target_label && <span className="notification-target">{notification.target_label}</span>}<time><i/>{relativeTime(notification.created_at)}</time></div>
                  <h3>{notification.title}</h3><p>{notification.message}</p>
                  <div className="notification-card-actions"><button className="notification-action-primary" onClick={() => { void markRead(notification); setOpen(false); onNavigate(notification.dashboard as NotificationDashboard); }}>View {notification.dashboard === 'inventory' ? 'inventory' : notification.dashboard}</button>{!notification.is_read && <button className="notification-read-action" onClick={() => void markRead(notification)}>Mark read</button>}</div>
                </div>
                <button className="notification-dismiss" aria-label={`Dismiss ${notification.title}`} title="Dismiss" onClick={() => void dismiss(notification)}><X size={14}/></button>
              </article>)}
            </section>;
          })}
        </div>
        <footer className="notification-footer"><span><i/>Synced with StockPulse</span><button onClick={() => { setLoading(true); void api.notifications().then(setNotifications).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : 'Notifications could not be refreshed.')).finally(() => setLoading(false)); }}><RefreshCw size={12}/>Refresh</button><span className="notification-footer-time"><Clock3 size={12}/>Auto-refresh 45s</span></footer>
      </aside>
    </div>}
  </>;
}
import { useEffect, useState } from 'react';
import { ArrowRight, BookOpen, CircleHelp, Package, Search, Settings, ShoppingCart, Users, WalletCards, Warehouse, X } from 'lucide-react';
import type { NotificationDashboard } from './api';
import './help-center.css';

type HelpTopic = {
  title: string;
  section: string;
  description: string;
  steps: string;
  dashboard: NotificationDashboard;
};

const topics: HelpTopic[] = [
  {
    title: 'Add or update a product',
    section: 'Products',
    description: 'Create catalog items with a SKU, category, supplier, prices, and starting quantity.',
    steps: 'Open Products, choose Add Product, complete the required fields, then save. To change an item later, use its row action.',
    dashboard: 'products',
  },
  {
    title: 'Review and adjust stock',
    section: 'Inventory',
    description: 'Check on-hand quantities, spot low stock, and record inventory adjustments.',
    steps: 'Open Inventory to review stock levels. Start an adjustment from the item row and enter the quantity change and reason before saving.',
    dashboard: 'inventory',
  },
  {
    title: 'Create and receive a purchase',
    section: 'Purchases',
    description: 'Record supplier orders and update inventory when goods arrive.',
    steps: 'Open Purchases, create an order, select the supplier and products, then save. Use Receive when the delivery arrives to update stock.',
    dashboard: 'purchases',
  },
  {
    title: 'Complete a point-of-sale checkout',
    section: 'Point of Sale',
    description: 'Build a cart, choose a customer and payment method, and record a sale.',
    steps: 'Open Point of Sale, find products by name or scan a barcode, adjust quantities, select payment, and choose Checkout.',
    dashboard: 'pos',
  },
  {
    title: 'Find sales and business reports',
    section: 'Reports',
    description: 'Review sales, purchases, and inventory performance for a selected period.',
    steps: 'Open Reports, select the report view and date range, then use the export control to download the displayed report.',
    dashboard: 'reports',
  },
  {
    title: 'Manage users and roles',
    section: 'Users & Roles',
    description: 'Create user accounts and control access through role permissions.',
    steps: 'Open Users & Roles to manage accounts and role assignments. Review the permissions for a role before applying it to a user.',
    dashboard: 'users',
  },
  {
    title: 'Configure business settings',
    section: 'Settings',
    description: 'Review operational defaults, security controls, and connected services.',
    steps: 'Open Settings, update the relevant setting, and save your changes. Configuration changes appear in the audit log.',
    dashboard: 'settings',
  },
];

const shortcuts: { label: string; dashboard: NotificationDashboard; Icon: typeof Package }[] = [
  { label: 'Products', dashboard: 'products', Icon: Package },
  { label: 'Inventory', dashboard: 'inventory', Icon: Warehouse },
  { label: 'Point of Sale', dashboard: 'pos', Icon: ShoppingCart },
  { label: 'Account', dashboard: 'account', Icon: WalletCards },
  { label: 'Users & Roles', dashboard: 'users', Icon: Users },
  { label: 'Settings', dashboard: 'settings', Icon: Settings },
];

export default function HelpCenter({ onClose, onNavigate }: {
  onClose: () => void;
  onNavigate: (dashboard: NotificationDashboard) => void;
}) {
  const [query, setQuery] = useState('');
  const normalizedQuery = query.trim().toLowerCase();
  const results = topics.filter((topic) =>
    `${topic.title} ${topic.section} ${topic.description} ${topic.steps}`.toLowerCase().includes(normalizedQuery),
  );

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', closeOnEscape);
    return () => document.removeEventListener('keydown', closeOnEscape);
  }, [onClose]);

  return <div className="catalog-overlay help-overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className="help-center" role="dialog" aria-modal="true" aria-labelledby="help-center-title">
      <header className="help-center-header">
        <span className="help-center-mark"><BookOpen size={18}/></span>
        <div><span className="catalog-eyebrow">STOCKPULSE SUPPORT</span><h2 id="help-center-title">Help Center</h2></div>
        <button className="catalog-icon-button" type="button" aria-label="Close Help Center" onClick={onClose}><X size={18}/></button>
      </header>
      <div className="help-center-search"><Search size={16}/><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search tasks, modules, and workflows" aria-label="Search help topics"/>{query && <button type="button" aria-label="Clear search" onClick={() => setQuery('')}><X size={14}/></button>}</div>
      <div className="help-center-body">
        <section className="help-shortcuts" aria-label="Quick links">
          <div className="help-section-heading"><div><span>GO TO</span><h3>Quick links</h3></div></div>
          <div className="help-shortcut-list">{shortcuts.map(({ label, dashboard, Icon }) => <button key={dashboard} onClick={() => onNavigate(dashboard)}><Icon size={15}/><span>{label}</span><ArrowRight size={13}/></button>)}</div>
        </section>
        <section className="help-guides" aria-label="Help topics">
          <div className="help-section-heading"><div><span>{normalizedQuery ? `${results.length} RESULTS` : 'WORKFLOWS'}</span><h3>{normalizedQuery ? 'Search results' : 'Common tasks'}</h3></div><CircleHelp size={16}/></div>
          {results.length ? <div className="help-topic-list">{results.map((topic) => <article className="help-topic" key={topic.title}>
            <div className="help-topic-heading"><h4>{topic.title}</h4><span>{topic.section}</span></div>
            <p>{topic.description}</p>
            <div className="help-topic-detail">{topic.steps}</div>
            <button onClick={() => onNavigate(topic.dashboard)}>Open {topic.section}<ArrowRight size={13}/></button>
          </article>)}</div> : <div className="help-empty"><Search size={19}/><strong>No matching help topics</strong><span>Try a module name or a different search.</span></div>}
        </section>
      </div>
      <footer className="help-center-footer"><span>Need access or account changes?</span><strong>Contact your StockPulse administrator.</strong></footer>
    </section>
  </div>;
}
import { useEffect, useMemo, useState } from 'react';
import { ArrowDownLeft, ArrowUpRight, Building2, Check, FileText, Mail, MapPin, Package, Phone, Plus, RefreshCw, Search, ShieldCheck, Truck, Users, Wallet, X } from 'lucide-react';
import { api, formatCurrency as currency, type Purchase, type Supplier, type SupplierDashboardData, type SupplierLedgerEntry } from './api';
import { useDataRevision } from './dataSync';
import './supplier-payments.css';

type SupplierTab = 'orders' | 'ledger' | 'catalog';
type SupplierDraft = Omit<Supplier, 'id' | 'supplier_code' | 'outstanding_balance' | 'lifetime_spend' | 'completed_orders' | 'on_time_delivery_rate' | 'created_at'>;
const dateLabel = (value: string) => new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value));

function SupplierPurchasePaymentForm({ purchase, onClose, onSaved }: {
  purchase: Purchase;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [amount, setAmount] = useState(purchase.remaining_balance);
  const [paymentMethod, setPaymentMethod] = useState<SupplierLedgerEntry['payment_method']>('');
  const [reference, setReference] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const remaining = Number(purchase.remaining_balance);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const paymentAmount = Number(amount);
    if (!Number.isFinite(paymentAmount) || paymentAmount <= 0 || paymentAmount > remaining) {
      setError(`Enter an amount greater than zero and no more than ${currency(purchase.remaining_balance)}.`);
      return;
    }
    if (!paymentMethod) {
      setError('Select how the supplier payment was made.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      await api.payPurchase(purchase.id, { amount: paymentAmount.toFixed(2), payment_method: paymentMethod, reference: reference.trim() });
      await onSaved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not record this supplier payment.');
    } finally {
      setSaving(false);
    }
  }

  return <div className="catalog-overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <form className="catalog-modal purchase-payment-modal" onSubmit={(event) => void submit(event)}>
      <div className="catalog-modal-heading"><div><span className="catalog-eyebrow">SUPPLIER PAYMENT</span><h2>Confirm payment</h2><p>Record how much the supplier received for {purchase.reference}.</p></div><button className="catalog-icon-button" type="button" onClick={onClose} aria-label="Close"><X size={18}/></button></div>
      <div className="purchase-payment-summary">
        <div><span>ORDER TOTAL</span><strong>{currency(purchase.total)}</strong></div>
        <div><span>ALREADY PAID</span><strong>{currency(purchase.paid_amount)}</strong></div>
        <div><span>REMAINING</span><strong>{currency(purchase.remaining_balance)}</strong></div>
      </div>
      <div className="purchase-payment-presets">
        <button type="button" className="catalog-button catalog-button-light" onClick={() => setAmount((remaining / 2).toFixed(2))}>Half of remaining</button>
        <button type="button" className="catalog-button catalog-button-light" onClick={() => setAmount(purchase.remaining_balance)}>Pay in full</button>
      </div>
      <label className="catalog-field">Amount received<input type="number" min="0.01" max={purchase.remaining_balance} step="0.01" required value={amount} onChange={(event) => setAmount(event.target.value)}/></label>
      <label className="catalog-field">Payment method<select required value={paymentMethod} onChange={(event) => setPaymentMethod(event.target.value as typeof paymentMethod)}><option value="" disabled>Select a payment method</option><option value="cash">Cash</option><option value="mobile">Mobile money</option><option value="card">Card</option><option value="transfer">Bank transfer</option><option value="check">Check</option></select></label>
      <label className="catalog-field">Payment reference <span className="purchase-payment-optional">(optional)</span><input maxLength={80} value={reference} onChange={(event) => setReference(event.target.value)} placeholder="Receipt, transfer, or transaction number"/></label>
      <p className="purchase-payment-confirmation">Confirming records the payment against this order and updates the supplier balance.</p>
      {error && <p className="catalog-form-error">{error}</p>}
      <div className="catalog-modal-actions"><button type="button" className="catalog-button catalog-button-light" onClick={onClose}>Cancel</button><button className="catalog-button catalog-button-primary" disabled={saving}>{saving ? 'Recording…' : 'Confirm payment'}</button></div>
    </form>
  </div>;
}

function SupplierForm({ supplier, onClose, onSaved }: {
  supplier: Supplier | null;
  onClose: () => void;
  onSaved: (supplier: Supplier) => Promise<void>;
}) {
  const [draft, setDraft] = useState({
    name: supplier?.name ?? '', contact_name: supplier?.contact_name ?? '', email: supplier?.email ?? '',
    phone: supplier?.phone ?? '', sector: supplier?.sector ?? '', account_manager: supplier?.account_manager ?? '',
    address: supplier?.address ?? '', tax_number: supplier?.tax_number ?? '', contract_number: supplier?.contract_number ?? '',
    payment_terms: supplier?.payment_terms ?? 'Net 30', lead_time_days: String(supplier?.lead_time_days ?? 3),
    is_active: supplier?.is_active ?? true,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const update = (key: keyof typeof draft, value: string | boolean) => setDraft((current) => ({ ...current, [key]: value }));

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError('');
    const payload: SupplierDraft = {
      ...draft,
      name: draft.name.trim(),
      contact_name: draft.contact_name.trim(),
      email: draft.email.trim(),
      phone: draft.phone.trim(),
      sector: draft.sector.trim(),
      account_manager: draft.account_manager.trim(),
      address: draft.address.trim(),
      tax_number: draft.tax_number.trim(),
      contract_number: draft.contract_number.trim(),
      lead_time_days: Number(draft.lead_time_days),
    };
    try {
      const saved = supplier ? await api.updateSupplier(supplier.id, payload) : await api.createSupplier(payload);
      await onSaved(saved);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save this supplier.');
    } finally {
      setSaving(false);
    }
  }

  return <div className="catalog-overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><form className="catalog-modal supplier-form-modal" onSubmit={submit}>
    <div className="catalog-modal-heading"><div><span className="catalog-eyebrow">SUPPLIER ACCOUNT</span><h2>{supplier ? 'Edit supplier' : 'Add supplier'}</h2><p>Maintain vendor contacts, terms, and delivery details.</p></div><button className="catalog-icon-button" type="button" onClick={onClose} aria-label="Close"><X size={18}/></button></div>
    <div className="catalog-form-row"><label className="catalog-field">Company name<input required maxLength={160} value={draft.name} onChange={(event) => update('name', event.target.value)}/></label><label className="catalog-field">Industry / sector<input maxLength={120} value={draft.sector} onChange={(event) => update('sector', event.target.value)}/></label></div>
    <div className="catalog-form-row"><label className="catalog-field">Primary contact<input maxLength={120} value={draft.contact_name} onChange={(event) => update('contact_name', event.target.value)}/></label><label className="catalog-field">Account manager<input maxLength={120} value={draft.account_manager} onChange={(event) => update('account_manager', event.target.value)}/></label></div>
    <div className="catalog-form-row"><label className="catalog-field">Work email<input type="email" maxLength={254} value={draft.email} onChange={(event) => update('email', event.target.value)}/></label><label className="catalog-field">Direct phone<input maxLength={40} value={draft.phone} onChange={(event) => update('phone', event.target.value)}/></label></div>
    <div className="catalog-form-row"><label className="catalog-field">Payment terms<input maxLength={40} value={draft.payment_terms} onChange={(event) => update('payment_terms', event.target.value)}/></label><label className="catalog-field">Lead time (days)<input type="number" min="0" step="1" value={draft.lead_time_days} onChange={(event) => update('lead_time_days', event.target.value)}/></label></div>
    <div className="catalog-form-row"><label className="catalog-field">Contract number<input maxLength={60} value={draft.contract_number} onChange={(event) => update('contract_number', event.target.value)}/></label><label className="catalog-field">Tax number<input maxLength={40} value={draft.tax_number} onChange={(event) => update('tax_number', event.target.value)}/></label></div>
    <label className="catalog-field">Business address<textarea rows={2} value={draft.address} onChange={(event) => update('address', event.target.value)}/></label>
    <label className="customer-checkbox"><input type="checkbox" checked={draft.is_active} onChange={(event) => update('is_active', event.target.checked)}/>Active supplier account</label>
    {error && <p className="catalog-form-error">{error}</p>}
    <div className="catalog-modal-actions"><button type="button" className="catalog-button catalog-button-light" onClick={onClose}>Cancel</button><button className="catalog-button catalog-button-primary" disabled={saving}>{saving ? 'Saving…' : supplier ? 'Save supplier' : 'Create supplier'}</button></div>
  </form></div>;
}

export default function SuppliersDashboard({ onOpenPurchases, onOpenInventory }: {
  onOpenPurchases: (supplierId: number) => void;
  onOpenInventory: () => void;
}) {
  const dataRevision = useDataRevision();
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<SupplierDashboardData | null>(null);
  const [tab, setTab] = useState<SupplierTab>('orders');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Supplier | null>(null);
  const [paymentPurchase, setPaymentPurchase] = useState<Purchase | null>(null);
  const [notice, setNotice] = useState('');

  async function loadSuppliers() {
    setLoading(true);
    setError('');
    try {
      const rows = await api.suppliers();
      setSuppliers(rows);
      if (selectedId) setDetail(await api.supplierDashboard(selectedId));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The supplier service could not be reached.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadSuppliers(); }, [dataRevision]);

  const filteredSuppliers = useMemo(() => {
    const term = query.trim().toLowerCase();
    return suppliers.filter((supplier) => `${supplier.name} ${supplier.supplier_code} ${supplier.contact_name} ${supplier.sector} ${supplier.email}`.toLowerCase().includes(term));
  }, [suppliers, query]);
  const totalSpend = suppliers.reduce((sum, supplier) => sum + Number(supplier.lifetime_spend), 0);
  const totalPayables = suppliers.reduce((sum, supplier) => sum + Number(supplier.outstanding_balance), 0);
  const completedOrders = suppliers.reduce((sum, supplier) => sum + supplier.completed_orders, 0);
  const onTimeRatings = suppliers.filter((supplier) => supplier.on_time_delivery_rate !== null);
  const averageOnTime = onTimeRatings.length ? onTimeRatings.reduce((sum, supplier) => sum + (supplier.on_time_delivery_rate ?? 0), 0) / onTimeRatings.length : null;

  async function openSupplier(supplierId: number) {
    setSelectedId(supplierId);
    setDetail(null);
    setTab('orders');
    setLoading(true);
    setError('');
    try {
      setDetail(await api.supplierDashboard(supplierId));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Supplier details could not be loaded.');
    } finally {
      setLoading(false);
    }
  }

  async function saveSupplier(supplier: Supplier) {
    setShowForm(false);
    setEditing(null);
    await loadSuppliers();
    await openSupplier(supplier.id);
    setNotice(`${supplier.name} supplier record saved.`);
  }

  async function recordPurchasePayment() {
    const reference = paymentPurchase?.reference;
    setPaymentPurchase(null);
    await loadSuppliers();
    setNotice(`Payment recorded${reference ? ` for ${reference}` : ''}; supplier balance updated.`);
  }

  const activeSupplier = detail?.supplier;

  return <>
    {!selectedId && <>
      <section className="catalog-heading suppliers-heading"><div><div className="catalog-breadcrumb">Procurement <span>›</span> <b>Suppliers</b></div><h1>Suppliers</h1><p>Manage vendor accounts, purchase performance, and accounts payable.</p></div><button className="catalog-button catalog-button-primary" onClick={() => setShowForm(true)}><Plus size={14}/>Add supplier</button></section>
      <section className="overview-metrics supplier-metrics"><article><span>ACTIVE SUPPLIERS</span><strong>{suppliers.filter((supplier) => supplier.is_active).length.toLocaleString()}</strong><small><Users size={13}/> {suppliers.length.toLocaleString()} vendor records</small></article><article><span>LIFETIME PROCUREMENT</span><strong>{currency(totalSpend)}</strong><small><Truck size={13}/> {completedOrders.toLocaleString()} received orders</small></article><article className="overview-alert-metric"><span>ACCOUNTS PAYABLE</span><strong>{currency(totalPayables)}</strong><small><Wallet size={13}/> Current open balance</small></article><article><span>ON-TIME DELIVERY</span><strong>{averageOnTime === null ? '—' : `${averageOnTime.toFixed(1)}%`}</strong><small><Check size={13}/> {onTimeRatings.length ? `${onTimeRatings.length} rated suppliers` : 'No delivery dates recorded'}</small></article></section>
      <section className="catalog-filter-panel supplier-list-filters"><div className="catalog-filter-row"><label className="catalog-search product-search"><Search size={15}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search supplier, account, contact, or sector"/></label><span className="inventory-result-count">{filteredSuppliers.length} suppliers</span></div></section>
      {loading && <section className="overview-state">Loading supplier accounts…</section>}
      {!loading && error && <section className="overview-state overview-error"><strong>Could not load suppliers</strong><span>{error}</span><button className="catalog-button catalog-button-light" onClick={() => void loadSuppliers()}><RefreshCw size={14}/>Retry</button></section>}
      {!loading && !error && <section className="catalog-table-panel supplier-table-panel"><div className="catalog-table-scroll"><table className="catalog-table supplier-table"><thead><tr><th>SUPPLIER</th><th>PRIMARY CONTACT</th><th>INDUSTRY</th><th>ORDERS</th><th>LIFETIME SPEND</th><th>AMOUNT DUE</th><th>ON-TIME</th><th>STATUS</th></tr></thead><tbody>{filteredSuppliers.map((supplier) => <tr key={supplier.id} onClick={() => void openSupplier(supplier.id)}><td><button className="supplier-account-link" onClick={() => void openSupplier(supplier.id)}><span className="supplier-avatar"><Building2 size={13}/></span><span><strong>{supplier.name}</strong><small>{supplier.supplier_code}</small></span></button></td><td><strong className="supplier-contact-name">{supplier.contact_name || '—'}</strong><small className="supplier-contact-email">{supplier.email}</small></td><td>{supplier.sector || '—'}</td><td>{supplier.completed_orders.toLocaleString()}</td><td><strong>{currency(supplier.lifetime_spend)}</strong></td><td className={Number(supplier.outstanding_balance) > 0 ? 'supplier-balance-due' : ''}>{currency(supplier.outstanding_balance)}</td><td>{supplier.on_time_delivery_rate === null ? '—' : `${supplier.on_time_delivery_rate}%`}</td><td><span className={`supplier-status ${supplier.is_active ? 'active' : ''}`}>{supplier.is_active ? 'Active' : 'Inactive'}</span></td></tr>)}{!filteredSuppliers.length && <tr><td colSpan={8} className="catalog-state">No suppliers found. Add a vendor account to begin tracking procurement.</td></tr>}</tbody></table></div><footer className="catalog-table-footer"><span>Showing <b>{filteredSuppliers.length}</b> of <b>{suppliers.length}</b> suppliers</span><button className="catalog-clear" onClick={() => setQuery('')}>Clear search</button></footer></section>}
    </>}

    {selectedId && <>
      {loading && !detail && <section className="overview-state">Loading supplier account…</section>}
      {!loading && error && !detail && <section className="overview-state overview-error"><strong>Could not load supplier account</strong><span>{error}</span><button className="catalog-button catalog-button-light" onClick={() => void openSupplier(selectedId)}><RefreshCw size={14}/>Retry</button></section>}
      {detail && activeSupplier && <>
        <div className="supplier-breadcrumb"><button onClick={() => { setSelectedId(null); setDetail(null); setError(''); }}><Building2 size={12}/>Suppliers</button><span>›</span><strong>{activeSupplier.name}</strong><code>{activeSupplier.supplier_code}</code><span className="supplier-verified"><ShieldCheck size={11}/>ERP supplier record verified</span></div>
        <section className="supplier-profile-hero"><div className="supplier-company-mark"><Building2 size={20}/></div><div className="supplier-profile-copy"><h1>{activeSupplier.name}</h1><div className="supplier-profile-meta"><span className={`supplier-status ${activeSupplier.is_active ? 'active' : ''}`}><i/>{activeSupplier.is_active ? 'Active' : 'Inactive'}</span><span>Primary preferred vendor</span>{activeSupplier.contract_number && <span><FileText size={11}/>{activeSupplier.contract_number}</span>}</div><p><Building2 size={12}/>{activeSupplier.sector || 'Industry not specified'}<span>·</span><span>ID: {activeSupplier.supplier_code}</span></p></div><div className="supplier-profile-actions"><button className="catalog-button catalog-button-primary" onClick={() => onOpenPurchases(activeSupplier.id)}><Truck size={14}/>Create purchase order</button><button className="catalog-button catalog-button-light" onClick={() => setEditing(activeSupplier)}>Edit supplier</button><button className="catalog-icon-button" onClick={onOpenInventory} aria-label="View inventory"><Package size={15}/></button></div></section>
        <section className="overview-metrics supplier-detail-metrics"><article><span>PROCUREMENT SPEND YTD</span><strong>{currency(detail.lifetime_spend)}</strong><small><Truck size={13}/> {detail.received_orders} orders received</small></article><article className="overview-alert-metric"><span>CURRENT AMOUNT DUE</span><strong>{currency(detail.outstanding_balance)}</strong><small><Wallet size={13}/> {activeSupplier.payment_terms}</small></article><article><span>ON-TIME DELIVERY RATE</span><strong>{activeSupplier.on_time_delivery_rate === null ? '—' : `${activeSupplier.on_time_delivery_rate}%`}</strong><small><Check size={13}/>{activeSupplier.on_time_delivery_rate === null ? 'Delivery dates not recorded' : `Lead time ${activeSupplier.lead_time_days} days`}</small></article><article><span>OPEN PURCHASE ORDERS</span><strong>{detail.purchase_orders.filter((purchase) => purchase.status === 'ordered').length.toLocaleString()}</strong><small><FileText size={13}/>{currency(detail.open_order_value)} committed</small></article></section>
        <div className="supplier-detail-layout"><aside className="supplier-info-column"><section className="overview-panel supplier-info-panel"><div className="supplier-panel-heading"><h2><Users size={14}/>Primary commercial contact</h2><button onClick={() => setEditing(activeSupplier)}>Edit</button></div><div className="supplier-info-manager"><span className="supplier-manager-avatar">{activeSupplier.account_manager ? activeSupplier.account_manager.slice(0, 1) : '—'}</span><span><small>ASSIGNED ACCOUNT MANAGER</small><strong>{activeSupplier.account_manager || 'Unassigned'}</strong></span></div><div className="supplier-info-list"><div><span><UserBadgeIcon/>Primary contact</span><strong>{activeSupplier.contact_name || '—'}</strong></div><div><span><Mail size={12}/>Direct invoicing &amp; PO email</span><strong>{activeSupplier.email || '—'}</strong></div><div><span><Phone size={12}/>Direct line / dispatch phone</span><strong>{activeSupplier.phone || '—'}</strong></div><div><span><MapPin size={12}/>Business address</span><strong>{activeSupplier.address || 'Not provided'}</strong></div></div><div className="supplier-tax-details"><div><small>TAX NUMBER</small><strong>{activeSupplier.tax_number || 'Not provided'}</strong></div><div><small>PAYMENT TERMS</small><strong>{activeSupplier.payment_terms}</strong></div></div></section><section className="overview-panel supplier-contract-panel"><div><span><FileText size={13}/>CONTRACT &amp; LEAD TIME</span><strong>{activeSupplier.contract_number || 'No contract reference'}</strong></div><small>Standard lead time · {activeSupplier.lead_time_days} business days</small></section></aside>
          <div className="supplier-detail-main"><section className="overview-panel supplier-records-panel"><div className="supplier-record-tabs" role="tablist" aria-label="Supplier records"><button className={tab === 'orders' ? 'active' : ''} onClick={() => setTab('orders')}><FileText size={13}/>Purchase orders <span>{detail.purchase_orders.length}</span></button><button className={tab === 'catalog' ? 'active' : ''} onClick={() => setTab('catalog')}><Package size={13}/>Supplied catalog <span>{detail.supplied_products.length}</span></button><button className={tab === 'ledger' ? 'active' : ''} onClick={() => setTab('ledger')}><Wallet size={13}/>Payment history <span>{detail.ledger_entries.length}</span></button></div>
            {tab === 'orders' && <div className="supplier-record-table-wrap"><table className="catalog-table supplier-record-table supplier-payment-table"><thead><tr><th>PO NUMBER</th><th>ORDER DATE</th><th>EXPECTED / RECEIVED</th><th>ORDER COMPOSITION</th><th>ORDER TOTAL</th><th>AMOUNT PAID</th><th>REMAINING</th><th>PAYMENT STATUS</th><th>ORDER STATUS</th><th>PAYMENT ACTION</th></tr></thead><tbody>{detail.purchase_orders.map((purchase) => <tr key={purchase.id}><td><strong className="supplier-order-ref">{purchase.reference}</strong></td><td>{dateLabel(purchase.ordered_at)}</td><td>{purchase.received_at ? dateLabel(purchase.received_at) : purchase.expected_delivery ? dateLabel(`${purchase.expected_delivery}T00:00:00`) : 'Not scheduled'}</td><td>{purchase.items.reduce((sum, item) => sum + item.quantity, 0)}× {purchase.items.slice(0, 2).map((item) => item.product_name).join(', ')}{purchase.items.length > 2 ? ` +${purchase.items.length - 2} more` : ''}</td><td><strong>{currency(purchase.total)}</strong></td><td><strong>{currency(purchase.paid_amount)}</strong></td><td className={Number(purchase.remaining_balance) > 0 && purchase.status === 'received' ? 'supplier-balance-due' : ''}><strong>{currency(purchase.remaining_balance)}</strong></td><td><span className={`purchase-payment-status ${purchase.payment_status}`}>{purchase.payment_status === 'not_due' ? 'Not due' : purchase.payment_status}</span></td><td><span className={`purchase-status ${purchase.status}`}>{purchase.status}</span></td><td>{purchase.status === 'received' && Number(purchase.remaining_balance) > 0 ? <button className="catalog-button catalog-button-light purchase-receive-button" onClick={() => setPaymentPurchase(purchase)}>Confirm payment</button> : <span className="catalog-muted">{purchase.payment_status === 'paid' ? 'Paid in full' : '—'}</span>}</td></tr>)}{!detail.purchase_orders.length && <tr><td colSpan={10} className="catalog-state">No purchase orders for this supplier yet.</td></tr>}</tbody></table></div>}
            {tab === 'catalog' && <div className="supplier-catalog-grid">{detail.supplied_products.map((product) => <article key={product.id}><span className="supplier-product-sku">SKU: {product.sku}</span><strong>{product.name}</strong><small>{product.category_name} · {product.quantity} in stock</small><div><span>Unit cost</span><b>{currency(product.cost_price)}</b></div><div><span>Lead time</span><b>{activeSupplier.lead_time_days} days</b></div><button onClick={onOpenInventory}><Package size={12}/>View inventory</button></article>)}{!detail.supplied_products.length && <p className="catalog-state">No products are currently linked to this supplier.</p>}</div>}
            {tab === 'ledger' && <div className="supplier-record-table-wrap"><table className="catalog-table supplier-record-table"><thead><tr><th>ACTIVITY</th><th>DATE</th><th>REFERENCE</th><th>NOTE</th><th>AMOUNT</th></tr></thead><tbody>{detail.ledger_entries.map((entry) => <tr key={entry.id}><td><span className={`supplier-ledger-icon ${entry.entry_type}`}>{entry.entry_type === 'payment' ? <ArrowDownLeft size={13}/> : <ArrowUpRight size={13}/>}</span>{entry.entry_type_display}</td><td>{dateLabel(entry.created_at)}</td><td>{entry.reference || entry.purchase_reference || '—'}</td><td>{entry.note || '—'}</td><td className={entry.entry_type === 'payment' || entry.entry_type === 'credit' ? 'supplier-credit-amount' : ''}>{entry.entry_type === 'payment' || entry.entry_type === 'credit' ? '−' : '+'}{currency(entry.amount)}</td></tr>)}{!detail.ledger_entries.length && <tr><td colSpan={5} className="catalog-state">No payable activity recorded yet.</td></tr>}</tbody></table></div>}
          </section><section className="overview-panel supplier-activity-panel"><div className="overview-panel-heading"><div><span>RECENT PROCUREMENT</span><h2>Latest supplier activity</h2></div><button className="overview-text-action" onClick={() => onOpenPurchases(activeSupplier.id)}>All purchases →</button></div>{detail.ledger_entries.slice(0, 4).map((entry) => <div className="supplier-activity-row" key={entry.id}><span className={`supplier-activity-dot ${entry.entry_type}`}/><span><strong>{entry.entry_type_display}{entry.purchase_reference ? ` · ${entry.purchase_reference}` : ''}</strong><small>{entry.note || entry.reference || 'Supplier account activity'}</small></span><time>{dateLabel(entry.created_at)}</time></div>)}{!detail.ledger_entries.length && <p className="overview-empty">Purchase receipts and payments will appear here.</p>}</section></div>
        </div>
      </>}
    </>}
    {notice && <div className="catalog-toast"><Check size={15}/>{notice}<button onClick={() => setNotice('')} aria-label="Dismiss"><X size={14}/></button></div>}
    {(showForm || editing) && <SupplierForm supplier={editing} onClose={() => { setShowForm(false); setEditing(null); }} onSaved={saveSupplier}/>}
    {paymentPurchase && <SupplierPurchasePaymentForm purchase={paymentPurchase} onClose={() => setPaymentPurchase(null)} onSaved={recordPurchasePayment}/>}
  </>;
}

function UserBadgeIcon() { return <Users size={12}/>; }
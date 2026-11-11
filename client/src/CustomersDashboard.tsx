import { useEffect, useMemo, useState } from 'react';
import { ArrowDownLeft, ArrowUpRight, BriefcaseBusiness, Building2, Check, CreditCard, Download, FileText, Mail, MapPin, Phone, Plus, RefreshCw, Search, ShoppingCart, UserRound, Users, Wallet, X } from 'lucide-react';
import { api, formatCurrency as currency, type Customer, type CustomerDashboardData, type Sale } from './api';
import { useDataRevision } from './dataSync';
import './customer-payments.css';

type CustomerTab = 'orders' | 'ledger' | 'account';
type CustomerDraft = Omit<Customer, 'id' | 'customer_code' | 'tax_exempt' | 'outstanding_balance' | 'lifetime_revenue' | 'completed_orders' | 'created_at'>;
const dateLabel = (value: string) => new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value));
const tierLabel = (tier: Customer['tier']) => tier.charAt(0).toUpperCase() + tier.slice(1);

function CustomerForm({ customer, onClose, onSaved }: {
  customer: Customer | null;
  onClose: () => void;
  onSaved: (customer: Customer) => Promise<void>;
}) {
  const [draft, setDraft] = useState({
    name: customer?.name ?? '', contact_name: customer?.contact_name ?? '', email: customer?.email ?? '',
    phone: customer?.phone ?? '', sector: customer?.sector ?? '', tier: customer?.tier ?? 'standard',
    account_manager: customer?.account_manager ?? '', billing_address: customer?.billing_address ?? '',
    shipping_address: customer?.shipping_address ?? '', tax_number: customer?.tax_number ?? '',
    payment_terms: customer?.payment_terms ?? 'Due on receipt',
    credit_limit: customer?.credit_limit ?? '0.00', is_active: customer?.is_active ?? true,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const update = (key: keyof typeof draft, value: string | boolean) => setDraft((current) => ({ ...current, [key]: value }));

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError('');
    const payload: CustomerDraft = {
      ...draft,
      name: draft.name.trim(),
      contact_name: draft.contact_name.trim(),
      email: draft.email.trim(),
      phone: draft.phone.trim(),
      sector: draft.sector.trim(),
      account_manager: draft.account_manager.trim(),
      billing_address: draft.billing_address.trim(),
      shipping_address: draft.shipping_address.trim(),
      tax_number: draft.tax_number.trim(),
    };
    try {
      const saved = customer ? await api.updateCustomer(customer.id, payload) : await api.createCustomer(payload);
      await onSaved(saved);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save this customer.');
    } finally {
      setSaving(false);
    }
  }

  return <div className="catalog-overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><form className="catalog-modal customer-form-modal" onSubmit={submit}>
    <div className="catalog-modal-heading"><div><span className="catalog-eyebrow">CUSTOMER ACCOUNT</span><h2>{customer ? 'Edit customer' : 'Add customer'}</h2><p>Maintain account, contact, and billing information.</p></div><button className="catalog-icon-button" type="button" onClick={onClose} aria-label="Close"><X size={18}/></button></div>
    <div className="catalog-form-row"><label className="catalog-field">Business / customer name<input required maxLength={180} value={draft.name} onChange={(event) => update('name', event.target.value)}/></label><label className="catalog-field">Industry / sector<input maxLength={120} value={draft.sector} onChange={(event) => update('sector', event.target.value)}/></label></div>
    <div className="catalog-form-row"><label className="catalog-field">Primary contact<input maxLength={120} value={draft.contact_name} onChange={(event) => update('contact_name', event.target.value)}/></label><label className="catalog-field">Account manager<input maxLength={120} value={draft.account_manager} onChange={(event) => update('account_manager', event.target.value)}/></label></div>
    <div className="catalog-form-row"><label className="catalog-field">Work email<input type="email" maxLength={254} value={draft.email} onChange={(event) => update('email', event.target.value)}/></label><label className="catalog-field">Phone<input maxLength={40} value={draft.phone} onChange={(event) => update('phone', event.target.value)}/></label></div>
    <div className="catalog-form-row"><label className="catalog-field">Customer tier<select value={draft.tier} onChange={(event) => update('tier', event.target.value as Customer['tier'])}><option value="standard">Standard</option><option value="growth">Growth</option><option value="enterprise">Enterprise</option></select></label><label className="catalog-field">Payment terms<input maxLength={40} value={draft.payment_terms} onChange={(event) => update('payment_terms', event.target.value)}/></label></div>
    <div className="catalog-form-row"><label className="catalog-field">Credit limit<input type="number" min="0" step="0.01" value={draft.credit_limit} onChange={(event) => update('credit_limit', event.target.value)}/></label><label className="catalog-field">Tax number<input maxLength={40} value={draft.tax_number} onChange={(event) => update('tax_number', event.target.value)}/></label></div>
    <label className="catalog-field">Billing address<textarea rows={2} value={draft.billing_address} onChange={(event) => update('billing_address', event.target.value)}/></label>
    <label className="catalog-field">Shipping address<textarea rows={2} value={draft.shipping_address} onChange={(event) => update('shipping_address', event.target.value)}/></label>
    <div className="customer-checkboxes"><label className="customer-checkbox"><input type="checkbox" checked={draft.is_active} onChange={(event) => update('is_active', event.target.checked)}/>Active account</label></div>
    {error && <p className="catalog-form-error">{error}</p>}
    <div className="catalog-modal-actions"><button type="button" className="catalog-button catalog-button-light" onClick={onClose}>Cancel</button><button className="catalog-button catalog-button-primary" disabled={saving}>{saving ? 'Saving…' : customer ? 'Save profile' : 'Create customer'}</button></div>
  </form></div>;
}

function CustomerPaymentForm({ customer, data, sale, onClose, onSaved }: {
  customer: Customer;
  data: CustomerDashboardData;
  sale: Sale | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const remainingBalance = sale?.remaining_balance ?? customer.outstanding_balance;
  const [amount, setAmount] = useState(remainingBalance);
  const [reference, setReference] = useState('');
  const [note, setNote] = useState('Account payment received');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const paymentAmount = Number(amount);
    const remaining = Number(remainingBalance);
    if (!Number.isFinite(paymentAmount) || paymentAmount <= 0 || paymentAmount > remaining) {
      setError(`Enter an amount greater than zero and no more than ${currency(remainingBalance)}.`);
      return;
    }
    setSaving(true);
    setError('');
    try {
      await api.receiveCustomerPayment(customer.id, {
        amount: paymentAmount.toFixed(2),
        reference: reference.trim(),
        note: note.trim(),
        ...(sale ? { sale: sale.id } : {}),
      });
      await onSaved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not record this payment.');
    } finally {
      setSaving(false);
    }
  }

  return <div className="catalog-overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><form className="catalog-modal customer-payment-modal" onSubmit={submit}>
    <div className="catalog-modal-heading"><div><span className="catalog-eyebrow">ACCOUNT LEDGER</span><h2>Confirm customer payment</h2><p>{sale ? `Record payment received for invoice ${sale.receipt_number}.` : 'Record the amount received against this customer’s account balance.'}</p></div><button className="catalog-icon-button" type="button" onClick={onClose} aria-label="Close"><X size={18}/></button></div>
    <div className="customer-payment-summary">
      <div><span>{sale ? 'INVOICE TOTAL' : 'ACCOUNT CHARGES'}</span><strong>{currency(sale?.total ?? data.account_charges)}</strong></div>
      <div><span>{sale ? 'INVOICE PAID' : 'ACCOUNT PAID'}</span><strong>{currency(sale?.paid_amount ?? data.account_payments)}</strong></div>
      <div><span>{sale ? 'INVOICE BALANCE' : 'ACCOUNT REMAINING'}</span><strong>{currency(remainingBalance)}</strong></div>
    </div>
    <div className="customer-payment-presets">
      <button type="button" className="catalog-button catalog-button-light" onClick={() => setAmount((Number(remainingBalance) / 2).toFixed(2))}>Half of remaining</button>
      <button type="button" className="catalog-button catalog-button-light" onClick={() => setAmount(remainingBalance)}>Pay in full</button>
    </div>
    <label className="catalog-field">Amount received<input type="number" min="0.01" max={remainingBalance} step="0.01" required value={amount} onChange={(event) => setAmount(event.target.value)}/></label>
    <label className="catalog-field">Reference<input maxLength={80} value={reference} onChange={(event) => setReference(event.target.value)} placeholder="Bank transfer or remittance ID"/></label>
    <label className="catalog-field">Note<input maxLength={240} value={note} onChange={(event) => setNote(event.target.value)}/></label>
    <p className="customer-payment-confirmation">Confirming records this payment, updates the remaining balance, and adds it to the customer ledger.</p>
    {error && <p className="catalog-form-error">{error}</p>}
    <div className="catalog-modal-actions"><button type="button" className="catalog-button catalog-button-light" onClick={onClose}>Cancel</button><button className="catalog-button catalog-button-primary" disabled={saving}>{saving ? 'Recording…' : 'Record payment'}</button></div>
  </form></div>;
}

export default function CustomersDashboard({ onStartSale, onOpenSales }: {
  onStartSale: (customerId: number) => void;
  onOpenSales: () => void;
}) {
  const dataRevision = useDataRevision();
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [detail, setDetail] = useState<CustomerDashboardData | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [tab, setTab] = useState<CustomerTab>('orders');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Customer | null>(null);
  const [showPayment, setShowPayment] = useState(false);
  const [paymentSale, setPaymentSale] = useState<Sale | null>(null);
  const [notice, setNotice] = useState('');

  async function loadCustomers() {
    setLoading(true);
    setError('');
    try {
      const rows = await api.customers();
      setCustomers(rows);
      if (selectedId) {
        setDetail(await api.customerDashboard(selectedId));
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The customer service could not be reached.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadCustomers(); }, [dataRevision]);

  const filteredCustomers = useMemo(() => {
    const term = query.trim().toLowerCase();
    return customers.filter((customer) => `${customer.name} ${customer.customer_code} ${customer.contact_name} ${customer.sector} ${customer.email}`.toLowerCase().includes(term));
  }, [customers, query]);
  const totalRevenue = customers.reduce((sum, customer) => sum + Number(customer.lifetime_revenue), 0);
  const totalBalance = customers.reduce((sum, customer) => sum + Number(customer.outstanding_balance), 0);
  const totalOrders = customers.reduce((sum, customer) => sum + customer.completed_orders, 0);

  async function openCustomer(customerId: number) {
    setSelectedId(customerId);
    setDetail(null);
    setTab('orders');
    setLoading(true);
    try {
      setDetail(await api.customerDashboard(customerId));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Customer details could not be loaded.');
    } finally {
      setLoading(false);
    }
  }

  async function saveCustomer(customer: Customer) {
    setShowForm(false);
    setEditing(null);
    await loadCustomers();
    await openCustomer(customer.id);
    setNotice(`${customer.name} profile saved.`);
  }

  async function recordPayment() {
    setShowPayment(false);
    await loadCustomers();
    setNotice('Payment recorded and account balance updated.');
  }

  const activeCustomer = detail?.customer;

  return <>
    {!selectedId && <>
      <section className="catalog-heading customers-heading"><div><div className="catalog-breadcrumb">Relationships <span>›</span> <b>Customers</b></div><h1>Customers</h1><p>Manage customer accounts, order history, and receivables.</p></div><button className="catalog-button catalog-button-primary" onClick={() => setShowForm(true)}><Plus size={14}/>Add customer</button></section>
      <section className="overview-metrics customer-metrics"><article><span>CUSTOMER ACCOUNTS</span><strong>{customers.length.toLocaleString()}</strong><small><Users size={13}/> {customers.filter((customer) => customer.is_active).length} active accounts</small></article><article><span>LIFETIME REVENUE</span><strong>{currency(totalRevenue)}</strong><small><ShoppingCart size={13}/> {totalOrders.toLocaleString()} completed orders</small></article><article className="overview-alert-metric"><span>OUTSTANDING BALANCE</span><strong>{currency(totalBalance)}</strong><small><Wallet size={13}/> Across customer accounts</small></article><article><span>ACCOUNT TIERS</span><strong>{new Set(customers.map((customer) => customer.tier)).size}</strong><small><BriefcaseBusiness size={13}/> Standard, growth, enterprise</small></article></section>
      <section className="catalog-filter-panel customer-list-filters"><div className="catalog-filter-row"><label className="catalog-search product-search"><Search size={15}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search name, account, contact, or sector"/></label><span className="inventory-result-count">{filteredCustomers.length} customers</span></div></section>
      {loading && <section className="overview-state">Loading customer accounts…</section>}
      {!loading && error && <section className="overview-state overview-error"><strong>Could not load customers</strong><span>{error}</span><button className="catalog-button catalog-button-light" onClick={() => void loadCustomers()}><RefreshCw size={14}/>Retry</button></section>}
      {!loading && !error && <section className="catalog-table-panel customer-table-panel"><div className="catalog-table-scroll"><table className="catalog-table customer-table"><thead><tr><th>ACCOUNT</th><th>PRIMARY CONTACT</th><th>INDUSTRY</th><th>ORDERS</th><th>LIFETIME REVENUE</th><th>BALANCE DUE</th><th>ACCOUNT TIER</th><th>STATUS</th></tr></thead><tbody>{filteredCustomers.map((customer) => <tr key={customer.id} onClick={() => void openCustomer(customer.id)}><td><button className="customer-account-link" onClick={() => void openCustomer(customer.id)}><span className="customer-avatar">{customer.name.slice(0, 1).toUpperCase()}</span><span><strong>{customer.name}</strong><small>{customer.customer_code}</small></span></button></td><td><strong className="customer-contact-name">{customer.contact_name || '—'}</strong><small className="customer-contact-email">{customer.email}</small></td><td>{customer.sector || '—'}</td><td>{customer.completed_orders.toLocaleString()}</td><td><strong>{currency(customer.lifetime_revenue)}</strong></td><td className={Number(customer.outstanding_balance) > 0 ? 'customer-balance-due' : ''}>{currency(customer.outstanding_balance)}</td><td><span className={`customer-tier ${customer.tier}`}>{tierLabel(customer.tier)}</span></td><td><span className={`customer-account-status ${customer.is_active ? 'active' : ''}`}>{customer.is_active ? 'Active' : 'Inactive'}</span></td></tr>)}{!filteredCustomers.length && <tr><td colSpan={8} className="catalog-state">No customers found. Add an account to get started.</td></tr>}</tbody></table></div><footer className="catalog-table-footer"><span>Showing <b>{filteredCustomers.length}</b> of <b>{customers.length}</b> customers</span><button className="catalog-clear" onClick={() => setQuery('')}>Clear search</button></footer></section>}
    </>}

    {selectedId && <>
      {loading && !detail && <section className="overview-state">Loading customer account…</section>}
      {!loading && error && !detail && <section className="overview-state overview-error"><strong>Could not load customer account</strong><span>{error}</span><button className="catalog-button catalog-button-light" onClick={() => void openCustomer(selectedId)}><RefreshCw size={14}/>Retry</button></section>}
      {detail && activeCustomer && <>
        <div className="customer-breadcrumb"><button onClick={() => { setSelectedId(null); setDetail(null); setError(''); }}><Users size={12}/>Customers</button><span>›</span><strong>{activeCustomer.name}</strong><code>{activeCustomer.customer_code}</code></div>
        <section className="customer-profile-hero"><div className="customer-company-mark"><Building2 size={20}/></div><div className="customer-profile-copy"><h1>{activeCustomer.name}</h1><div className="customer-profile-meta"><span className="customer-account-status active"><i/>Active</span><span>{tierLabel(activeCustomer.tier)} account</span></div><p><BriefcaseBusiness size={12}/>{activeCustomer.sector || 'Industry not specified'}<span>·</span><span>ID: {activeCustomer.customer_code}</span></p></div><div className="customer-profile-actions"><button className="catalog-button catalog-button-primary" onClick={() => onStartSale(activeCustomer.id)}><ShoppingCart size={14}/>New sale</button>{Number(activeCustomer.outstanding_balance) > 0 && <button className="catalog-button catalog-button-light" onClick={() => setShowPayment(true)}><CreditCard size={14}/>Record payment</button>}<button className="catalog-button catalog-button-light" onClick={() => setEditing(activeCustomer)}>Edit profile</button><button className="catalog-icon-button" onClick={onOpenSales} aria-label="Open sales reports"><Download size={15}/></button></div></section>
        <section className="overview-metrics customer-detail-metrics"><article><span>LIFETIME REVENUE</span><strong>{currency(detail.lifetime_revenue)}</strong><small><TrendingUpIcon/>Total recorded sales</small></article><article><span>AMOUNT PAID</span><strong>{currency(detail.total_paid_amount)}</strong><small><CreditCard size={13}/>Across all customer sales</small></article><article className="overview-alert-metric"><span>REMAINING ON SALES</span><strong>{currency(detail.total_remaining_balance)}</strong><small><Wallet size={13}/>Account balance {currency(detail.outstanding_balance)}</small></article><article><span>COMPLETED ORDERS</span><strong>{detail.completed_orders.toLocaleString()}</strong><small><ShoppingCart size={13}/>Average order {currency(detail.completed_orders ? Number(detail.lifetime_revenue) / detail.completed_orders : 0)}</small></article></section>
        <div className="customer-detail-layout">
          <aside className="customer-info-column">
            <section className="overview-panel customer-info-panel"><div className="customer-panel-heading"><h2><UserRound size={14}/>Customer information</h2><button onClick={() => setEditing(activeCustomer)}>Edit</button></div><div className="customer-info-manager"><span className="customer-manager-avatar">{activeCustomer.account_manager ? activeCustomer.account_manager.slice(0, 1) : '—'}</span><span><small>ACCOUNT MANAGER</small><strong>{activeCustomer.account_manager || 'Unassigned'}</strong></span></div><div className="customer-info-list"><div><span><UserRound size={12}/>Contact</span><strong>{activeCustomer.contact_name || '—'}</strong></div><div><span><Mail size={12}/>Work email</span><strong>{activeCustomer.email || '—'}</strong></div><div><span><Phone size={12}/>Direct phone</span><strong>{activeCustomer.phone || '—'}</strong></div><div><span><MapPin size={12}/>Billing address</span><strong>{activeCustomer.billing_address || 'Not provided'}</strong></div><div><span><MapPin size={12}/>Shipping address</span><strong>{activeCustomer.shipping_address || 'Same as billing'}</strong></div></div><div className="customer-tax-details"><div><small>TAX ID</small><strong>{activeCustomer.tax_number || 'Not provided'}</strong></div><div><small>TERMS</small><strong>{activeCustomer.payment_terms}</strong></div></div></section>
            <section className="overview-panel customer-credit-panel"><div><span><Wallet size={13}/>CREDIT UTILIZATION</span><strong>{currency(activeCustomer.outstanding_balance)} <small>of {currency(activeCustomer.credit_limit)}</small></strong></div><div className="customer-credit-track"><i style={{ width: `${Math.min(Number(activeCustomer.credit_limit) ? Number(activeCustomer.outstanding_balance) / Number(activeCustomer.credit_limit) * 100 : 0, 100)}%` }}/></div><small>{activeCustomer.credit_limit && Number(activeCustomer.credit_limit) > 0 ? `${Math.round(Number(activeCustomer.outstanding_balance) / Number(activeCustomer.credit_limit) * 100)}% of credit limit used` : 'No credit line assigned'}</small></section>
          </aside>
          <div className="customer-detail-main">
            <section className="overview-panel customer-records-panel"><div className="customer-record-tabs" role="tablist" aria-label="Customer records"><button className={tab === 'orders' ? 'active' : ''} onClick={() => setTab('orders')}><FileText size={13}/>Order history &amp; invoices <span>{detail.sales.length + detail.bottle_purchase_orders.length + detail.client_material_purchase_orders.length}</span></button><button className={tab === 'ledger' ? 'active' : ''} onClick={() => setTab('ledger')}><Wallet size={13}/>Ledger &amp; statements <span>{detail.ledger_entries.length}</span></button><button className={tab === 'account' ? 'active' : ''} onClick={() => setTab('account')}><BriefcaseBusiness size={13}/>Account profile</button></div>
              {tab === 'orders' && <>
                <div className="customer-record-table-wrap"><table className="catalog-table customer-record-table customer-order-payment-table"><thead><tr><th>INVOICE #</th><th>ORDER DATE</th><th>ITEMS SOLD</th><th>PAYMENT METHOD</th><th>ORDER TOTAL</th><th>AMOUNT PAID</th><th>REMAINING</th><th>PAYMENT ACTION</th></tr></thead><tbody>{detail.sales.map((sale) => <tr key={sale.id}><td>{Number(sale.remaining_balance) > 0 ? <button type="button" className="customer-invoice-ref customer-invoice-payment-link" title="Click to enter a payment for this invoice" aria-label={`Record payment for invoice ${sale.receipt_number}`} onClick={() => { setPaymentSale(sale); setShowPayment(true); }}>{sale.receipt_number}</button> : <strong className="customer-invoice-ref">{sale.receipt_number}</strong>}<small>{sale.customer_name}</small></td><td>{dateLabel(sale.created_at)}</td><td><div className="customer-sold-items">{sale.items.map((item) => <div key={item.id}><strong>{item.product_name}</strong><small>{item.product_sku} · {item.quantity} × {currency(item.unit_price)} = {currency(item.line_total)}</small></div>)}</div></td><td><span className={`customer-payment-badge ${sale.payment_method}`}>{sale.payment_method_display}</span><small className={`customer-sale-payment-status ${sale.payment_status}`}>{sale.payment_status}</small></td><td><strong>{currency(sale.total)}</strong></td><td><strong>{currency(sale.paid_amount)}</strong></td><td className={Number(sale.remaining_balance) > 0 ? 'customer-balance-due' : ''}><strong>{currency(sale.remaining_balance)}</strong></td><td>{Number(sale.remaining_balance) > 0 ? <button className="catalog-button catalog-button-light customer-sale-pay-button" onClick={() => { setPaymentSale(sale); setShowPayment(true); }}>Record payment</button> : <span className="catalog-muted">{sale.payment_status === 'paid' ? 'Paid in full' : '—'}</span>}</td></tr>)}{!detail.sales.length && <tr><td colSpan={8} className="catalog-state">No sales invoices recorded for this account yet.</td></tr>}</tbody></table></div>
                <div className="customer-po-history-heading"><strong>Purchase order delivery history</strong><span>Bottle deliveries and client-supplied material receipts</span></div>
                <div className="customer-record-table-wrap"><table className="catalog-table customer-record-table"><thead><tr><th>PO / DELIVERY</th><th>DATE</th><th>PRODUCT / MATERIAL</th><th>QUANTITY</th><th>STATUS</th></tr></thead><tbody>
                  {detail.bottle_purchase_orders.flatMap((order) => order.deliveries.flatMap((delivery) => delivery.items.map((item) => <tr key={`bottle-${delivery.id}-${item.id}`}><td><strong>{order.reference}</strong><small>{delivery.reference}</small></td><td>{dateLabel(delivery.delivered_at)}</td><td><strong>{item.product_name}</strong><small>{item.product_sku}</small></td><td>{item.quantity.toLocaleString()} {item.unit}</td><td><span className="customer-payment-badge cash">Delivered</span></td></tr>)))}
                  {detail.client_material_purchase_orders.flatMap((order) => order.receipts.map((receipt) => <tr key={`material-${receipt.id}`}><td><strong>{order.reference}</strong><small>{receipt.reference}</small></td><td>{dateLabel(receipt.received_at)}</td><td><strong>{order.material_name}</strong><small>Client-supplied material</small></td><td>{Number(receipt.quantity).toLocaleString()} {order.material_unit}</td><td><span className="customer-payment-badge cash">Received</span></td></tr>))}
                  {!detail.bottle_purchase_orders.some((order) => order.deliveries.some((delivery) => delivery.items.length > 0)) && !detail.client_material_purchase_orders.some((order) => order.receipts.length > 0) && <tr><td colSpan={5} className="catalog-state">No purchase order deliveries or material receipts recorded for this account.</td></tr>}
                </tbody></table></div>
              </>}
              {tab === 'ledger' && <div className="customer-record-table-wrap"><table className="catalog-table customer-record-table"><thead><tr><th>ACTIVITY</th><th>DATE</th><th>REFERENCE</th><th>NOTE</th><th>AMOUNT</th></tr></thead><tbody>{detail.ledger_entries.map((entry) => <tr key={entry.id}><td><span className={`customer-ledger-icon ${entry.entry_type}`} >{entry.entry_type === 'payment' ? <ArrowDownLeft size={13}/> : <ArrowUpRight size={13}/>}</span>{entry.entry_type_display}</td><td>{dateLabel(entry.created_at)}</td><td>{entry.reference || entry.sale_reference || '—'}</td><td>{entry.note || '—'}</td><td className={entry.entry_type === 'payment' || entry.entry_type === 'credit' ? 'customer-credit-amount' : ''}>{entry.entry_type === 'payment' || entry.entry_type === 'credit' ? '−' : '+'}{currency(entry.amount)}</td></tr>)}{!detail.ledger_entries.length && <tr><td colSpan={5} className="catalog-state">No account ledger activity yet.</td></tr>}</tbody></table></div>}
              {tab === 'account' && <div className="customer-account-fields"><div><span>Account tier</span><strong>{tierLabel(activeCustomer.tier)}</strong></div><div><span>Industry</span><strong>{activeCustomer.sector || '—'}</strong></div><div><span>Payment terms</span><strong>{activeCustomer.payment_terms}</strong></div><div><span>Approved credit limit</span><strong>{currency(activeCustomer.credit_limit)}</strong></div><div><span>Tax treatment</span><strong>{activeCustomer.tax_number ? `Tax ID ${activeCustomer.tax_number}` : 'Standard'}</strong></div><div><span>Account created</span><strong>{dateLabel(activeCustomer.created_at)}</strong></div></div>}
            </section>
            <section className="overview-panel customer-activity-panel"><div className="overview-panel-heading"><div><span>ACCOUNT ACTIVITY</span><h2>Recent account activity &amp; audit log</h2></div><button className="overview-text-action" onClick={() => setTab('ledger')}>Full account ledger →</button></div>{detail.ledger_entries.slice(0, 4).map((entry) => <div className="customer-activity-row" key={entry.id}><span className={`customer-activity-dot ${entry.entry_type}`}/><span><strong>{entry.entry_type_display}{entry.sale_reference ? ` · ${entry.sale_reference}` : ''}</strong><small>{entry.note || entry.reference || 'Account activity recorded'}</small></span><time>{dateLabel(entry.created_at)}</time></div>)}{!detail.ledger_entries.length && <p className="overview-empty">Customer sales and payments will appear here.</p>}</section>
          </div>
        </div>
      </>}
    </>}
    {notice && <div className="catalog-toast"><Check size={15}/>{notice}<button onClick={() => setNotice('')} aria-label="Dismiss"><X size={14}/></button></div>}
    {(showForm || editing) && <CustomerForm customer={editing} onClose={() => { setShowForm(false); setEditing(null); }} onSaved={saveCustomer}/>}
    {showPayment && activeCustomer && detail && <CustomerPaymentForm customer={activeCustomer} data={detail} sale={paymentSale} onClose={() => { setShowPayment(false); setPaymentSale(null); }} onSaved={async () => { setShowPayment(false); setPaymentSale(null); await recordPayment(); }}/>}
  </>;
}

function TrendingUpIcon() { return <ArrowUpRight size={13}/>; }
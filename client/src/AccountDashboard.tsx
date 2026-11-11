import { useEffect, useMemo, useState } from 'react';
import { ArrowDownLeft, ArrowUpRight, CircleAlert, CreditCard, RefreshCw, Search, Smartphone, WalletCards } from 'lucide-react';
import { api, formatCurrency as currency, type Purchase, type Sale, type SupplierLedgerEntry } from './api';
import { useDataRevision } from './dataSync';

type PaymentFilter = 'all' | 'cash' | 'mobile' | 'card' | 'transfer' | 'check' | 'account' | 'unspecified';
type ActivityItem = { id: string; name: string; sku: string; quantity: number; unitPrice: string; total: string };
type ActivityRow = {
  id: string;
  type: 'sale' | 'purchase';
  reference: string;
  counterparty: string;
  date: string;
  total: string;
  paid: string;
  outstanding: string;
  methodLabels: Array<{ method: string; amount?: string }>;
  items: ActivityItem[];
};

const paymentFilters: Array<{ value: PaymentFilter; label: string }> = [
  { value: 'all', label: 'All payment methods' },
  { value: 'cash', label: 'Cash' },
  { value: 'mobile', label: 'Mobile money' },
  { value: 'card', label: 'Card' },
  { value: 'transfer', label: 'Bank transfer' },
  { value: 'check', label: 'Check' },
  { value: 'account', label: 'On account' },
  { value: 'unspecified', label: 'Unspecified' },
];

const methodNames: Record<Exclude<PaymentFilter, 'all' | 'unspecified'>, string> = {
  cash: 'Cash',
  mobile: 'Mobile money',
  card: 'Card',
  transfer: 'Bank transfer',
  check: 'Check',
  account: 'On account',
};

function paymentLabel(method: SupplierLedgerEntry['payment_method']) {
  return method ? methodNames[method] : 'Unspecified';
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Date unavailable' : date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

function saleRow(sale: Sale): ActivityRow {
  const payments = sale.payments.map((payment) => ({
    method: payment.payment_method ? methodNames[payment.payment_method] : 'Unspecified',
    amount: payment.amount,
  }));
  return {
    id: `sale-${sale.id}`,
    type: 'sale',
    reference: sale.receipt_number,
    counterparty: sale.customer_name || 'Walk-in Customer',
    date: sale.created_at,
    total: sale.total,
    paid: sale.paid_amount,
    outstanding: sale.remaining_balance,
    methodLabels: sale.payment_method === 'account'
      ? payments.length ? payments : [{ method: 'On account' }]
      : [{ method: methodNames[sale.payment_method], amount: sale.paid_amount }],
    items: sale.items.map((item) => ({
      id: String(item.id),
      name: item.product_name,
      sku: item.product_sku,
      quantity: item.quantity,
      unitPrice: item.unit_price,
      total: item.line_total,
    })),
  };
}

function purchaseRow(purchase: Purchase): ActivityRow {
  const payments = purchase.payments.map((payment) => ({
    method: paymentLabel(payment.payment_method),
    amount: payment.amount,
  }));
  return {
    id: `purchase-${purchase.id}`,
    type: 'purchase',
    reference: purchase.reference,
    counterparty: purchase.supplier_name,
    date: purchase.received_at ?? purchase.ordered_at,
    total: purchase.total,
    paid: purchase.paid_amount,
    outstanding: purchase.remaining_balance,
    methodLabels: payments.length ? payments : [{ method: 'On account' }],
    items: purchase.items.map((item) => ({
      id: String(item.id),
      name: item.product_name,
      sku: item.product_sku,
      quantity: item.quantity,
      unitPrice: item.unit_cost,
      total: item.line_total,
    })),
  };
}

function matchesPayment(row: ActivityRow, filter: PaymentFilter) {
  if (filter === 'all') return true;
  if (filter === 'account') return row.type === 'sale'
    ? Number(row.outstanding) > 0 || row.methodLabels.some((payment) => payment.method.toLowerCase().includes('account'))
    : Number(row.outstanding) > 0;
  if (filter === 'unspecified') return row.type === 'purchase'
    && row.methodLabels.some((payment) => payment.method === 'Unspecified');
  const label = methodNames[filter];
  return row.methodLabels.some((payment) => payment.method === label);
}

export default function AccountDashboard() {
  const dataRevision = useDataRevision();
  const [sales, setSales] = useState<Sale[]>([]);
  const [purchases, setPurchases] = useState<Purchase[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [paymentFilter, setPaymentFilter] = useState<PaymentFilter>('all');
  const [historyRange, setHistoryRange] = useState<'all' | '7' | '30' | '365'>('all');
  const [search, setSearch] = useState('');

  async function loadActivity() {
    setLoading(true);
    setError('');
    try {
      const [saleRows, purchaseRows] = await Promise.all([api.sales(), api.purchases()]);
      setSales(saleRows);
      setPurchases(purchaseRows);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Account activity could not be loaded.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadActivity(); }, [dataRevision]);

  const rows = useMemo(() => {
    const term = search.trim().toLowerCase();
    const minimumDate = historyRange === 'all' ? 0 : Date.now() - Number(historyRange) * 24 * 60 * 60 * 1000;
    return [
      ...sales.map(saleRow),
      ...purchases.filter((purchase) => purchase.status === 'received').map(purchaseRow),
    ].filter((row) => {
      const matchesDate = new Date(row.date).getTime() >= minimumDate;
      const matchesSearch = !term || `${row.reference} ${row.counterparty} ${row.items.map((item) => `${item.name} ${item.sku}`).join(' ')}`.toLowerCase().includes(term);
      return matchesDate && matchesSearch && matchesPayment(row, paymentFilter);
    }).sort((left, right) => new Date(right.date).getTime() - new Date(left.date).getTime());
  }, [sales, purchases, search, paymentFilter, historyRange]);

  const totals = useMemo(() => rows.reduce((result, row) => {
    if (row.type === 'sale') result.sales += Number(row.total);
    else {
      result.purchases += Number(row.total);
      result.paid += row.methodLabels.reduce((sum, payment) => {
        const includesPayment = paymentFilter === 'all'
          || (paymentFilter !== 'account' && paymentFilter !== 'unspecified' && payment.method === methodNames[paymentFilter])
          || (paymentFilter === 'unspecified' && payment.method === 'Unspecified');
        return includesPayment ? sum + Number(payment.amount ?? 0) : sum;
      }, 0);
      result.outstanding += Number(row.outstanding);
    }
    return result;
  }, { sales: 0, purchases: 0, paid: 0, outstanding: 0 }), [rows, paymentFilter]);

  return <>
    <section className="catalog-heading account-heading">
      <div><div className="catalog-breadcrumb">Finance <span>›</span> <b>Account activity</b></div><h1>Account</h1><p>Review items sold and purchased, transaction values, and how each sale or supplier payment was made.</p></div>
      <div className="catalog-heading-actions"><span className="reports-live"><i/>Updates when records are saved</span></div>
    </section>

    <section className="account-metrics" aria-label="Account totals">
      <article><span>SALES</span><strong>{currency(totals.sales)}</strong><small><ArrowUpRight size={13}/>Customer transactions</small></article>
      <article><span>ITEMS PURCHASED</span><strong>{currency(totals.purchases)}</strong><small><ArrowDownLeft size={13}/>Received supplier orders</small></article>
      <article><span>PAID TO SUPPLIERS</span><strong>{currency(totals.paid)}</strong><small><WalletCards size={13}/>Recorded supplier payments</small></article>
      <article className={totals.outstanding ? 'account-outstanding' : ''}><span>SUPPLIER BALANCE DUE</span><strong>{currency(totals.outstanding)}</strong><small><CircleAlert size={13}/>Unpaid purchase balance</small></article>
    </section>

    <section className="account-activity-panel">
      <div className="account-activity-heading">
        <div><span>TRANSACTION LEDGER</span><h2>Items sold and bought</h2><p>{rows.length.toLocaleString()} transaction{rows.length === 1 ? '' : 's'} in this view</p></div>
        <div className="account-activity-filters">
          <label className="catalog-search account-search"><Search size={14}/><input aria-label="Search account activity" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search items, SKU, or reference"/></label>
          <label className="catalog-select"><select aria-label="Filter by payment method" value={paymentFilter} onChange={(event) => setPaymentFilter(event.target.value as PaymentFilter)}>{paymentFilters.map((filter) => <option key={filter.value} value={filter.value}>{filter.label}</option>)}</select></label>
          <label className="catalog-select"><select aria-label="Filter transaction history" value={historyRange} onChange={(event) => setHistoryRange(event.target.value as typeof historyRange)}><option value="all">All time</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="365">Last year</option></select></label>
          <button className="catalog-icon-button" type="button" onClick={() => void loadActivity()} aria-label="Refresh account activity" title="Refresh account activity"><RefreshCw size={15}/></button>
        </div>
      </div>
      {loading && <section className="overview-state">Loading account activity…</section>}
      {!loading && error && <section className="overview-state overview-error"><strong>Could not load account activity</strong><span>{error}</span><button className="catalog-button catalog-button-light" onClick={() => void loadActivity()}><RefreshCw size={14}/>Retry</button></section>}
      {!loading && !error && rows.length === 0 && <p className="account-empty">No sales or received purchases match these filters.</p>}
      {!loading && !error && rows.length > 0 && <div className="account-table-scroll">
        <table className="account-table">
          <thead><tr><th>TRANSACTION</th><th>DATE</th><th>CUSTOMER / SUPPLIER</th><th>ITEMS</th><th>PAYMENT METHOD</th><th>VALUE</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.id}>
            <td><span className={`account-type ${row.type}`}><i>{row.type === 'sale' ? <ArrowUpRight size={12}/> : <ArrowDownLeft size={12}/>}</i>{row.type === 'sale' ? 'Sale' : 'Purchase'}</span><strong className="account-reference">{row.reference}</strong></td>
            <td>{formatDate(row.date)}</td>
            <td>{row.counterparty}</td>
            <td><div className="account-items">{row.items.map((item) => <span key={item.id}><strong>{item.quantity} × {item.name}</strong><small>{item.sku} · {currency(item.unitPrice)} each · {currency(item.total)}</small></span>)}</div></td>
            <td><div className="account-methods">{row.methodLabels.map((payment, index) => <span className="account-method" key={`${payment.method}-${index}`}>{payment.method}{payment.amount ? <strong>{currency(payment.amount)}</strong> : null}</span>)}{Number(row.outstanding) > 0 && row.type === 'purchase' && <span className="account-method account-due">Balance due<strong>{currency(row.outstanding)}</strong></span>}</div></td>
            <td><strong className="account-amount">{currency(row.total)}</strong>{row.type === 'sale' && Number(row.outstanding) > 0 && <small className="account-balance">Due {currency(row.outstanding)}</small>}</td>
          </tr>)}</tbody>
        </table>
      </div>}
      <div className="account-legend"><span><ArrowUpRight size={13}/> Sales use the payment method selected at checkout.</span><span><CreditCard size={13}/> Purchases show every recorded supplier payment method.</span><span><Smartphone size={13}/> Older supplier payments without a recorded method appear as unspecified.</span></div>
    </section>
  </>;
}

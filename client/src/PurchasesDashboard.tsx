import { useEffect, useMemo, useState } from 'react';
import { ArrowDownToLine, Check, ChevronDown, CircleAlert, FileText, Package, Plus, RefreshCw, Search, Truck, X } from 'lucide-react';
import { api, formatCurrency as currency, type InventoryAdjustment, type Product, type Purchase, type PurchaseSummary, type Supplier, type SupplierLedgerEntry } from './api';
import { useDataRevision } from './dataSync';

type PurchaseStatusFilter = 'All orders' | 'Ordered' | 'Received' | 'Cancelled';
type PurchaseLineDraft = { product: string; quantity: string; unit_cost: string };
const PURCHASE_HISTORY_RANGES = [
  { value: '1d', label: '1 day', days: 1 },
  { value: '1w', label: '1 week', days: 7 },
  { value: '1m', label: '1 month', days: 30 },
  { value: '3m', label: '3 months', days: 90 },
  { value: '6m', label: '6 months', days: 180 },
  { value: '1y', label: '1 year', days: 365 },
  { value: '2y', label: '2 years', days: 730 },
  { value: '5y', label: '5 years', days: 1825 },
  { value: '10y', label: '10 years', days: 3650 },
  { value: '50y', label: '50 years', days: 18250 },
  { value: '100y', label: '100 years', days: 36500 },
  { value: '200y', label: '200 years', days: 73000 },
] as const;
type PurchaseHistoryRange = typeof PURCHASE_HISTORY_RANGES[number]['value'];
const daysForPurchaseRange = (range: PurchaseHistoryRange) => PURCHASE_HISTORY_RANGES.find((option) => option.value === range)!.days;
const currentMonth = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
};
const currentDate = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
};
const localDateValue = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
const dateLabel = (value: string) => new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value));

function PurchaseForm({ products, suppliers, initialSupplierId, onClose, onSaved }: {
  products: Product[];
  suppliers: Supplier[];
  initialSupplierId?: number | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [supplierId, setSupplierId] = useState(String(initialSupplierId ?? suppliers[0]?.id ?? ''));
  const [expectedDelivery, setExpectedDelivery] = useState('');
  const [notes, setNotes] = useState('');
  const [lines, setLines] = useState<PurchaseLineDraft[]>([{ product: '', quantity: '1', unit_cost: '0.00' }]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const total = lines.reduce((sum, line) => sum + Number(line.quantity || 0) * Number(line.unit_cost || 0), 0);

  function updateLine(index: number, key: keyof PurchaseLineDraft, value: string) {
    setLines((current) => current.map((line, lineIndex) => {
      if (lineIndex !== index) return line;
      if (key === 'product') {
        const product = products.find((item) => item.id === Number(value));
        return { ...line, product: value, unit_cost: product?.cost_price ?? line.unit_cost };
      }
      return { ...line, [key]: value };
    }));
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!supplierId || lines.some((line) => !line.product)) { setError('Choose a supplier and a product for every line.'); return; }
    setSaving(true);
    setError('');
    try {
      await api.createPurchase({
        supplier: Number(supplierId),
        notes: notes.trim(),
        expected_delivery: expectedDelivery || null,
        items: lines.map((line) => ({ product: Number(line.product), quantity: Number(line.quantity), unit_cost: line.unit_cost })),
      });
      await onSaved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not create this purchase order.');
    } finally {
      setSaving(false);
    }
  }

  return <div className="catalog-overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <form className="catalog-modal purchase-modal" onSubmit={submit}>
      <div className="catalog-modal-heading"><div><span className="catalog-eyebrow">PROCUREMENT</span><h2>New purchase order</h2><p>Stock changes only after the order is received.</p></div><button className="catalog-icon-button" type="button" onClick={onClose} aria-label="Close"><X size={18}/></button></div>
      <label className="catalog-field">Supplier<select required value={supplierId} onChange={(event) => setSupplierId(event.target.value)}><option value="">Select a supplier</option>{suppliers.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}</select></label>
      <div className="purchase-lines-heading"><strong>Order items</strong><button type="button" className="catalog-clear" onClick={() => setLines((current) => [...current, { product: '', quantity: '1', unit_cost: '0.00' }])}><Plus size={13}/>Add item</button></div>
      <div className="purchase-draft-lines">{lines.map((line, index) => <div className="purchase-draft-line" key={index}>
        <label className="catalog-field"><span>Product</span><select required value={line.product} onChange={(event) => updateLine(index, 'product', event.target.value)}><option value="">Choose product</option>{products.filter((product) => product.is_active).map((product) => <option key={product.id} value={product.id}>{product.name} · {product.sku}</option>)}</select></label>
        <label className="catalog-field"><span>Qty</span><input type="number" min="1" step="1" required value={line.quantity} onChange={(event) => updateLine(index, 'quantity', event.target.value)}/></label>
        <label className="catalog-field"><span>Unit cost</span><input type="number" min="0" step="0.01" required value={line.unit_cost} onChange={(event) => updateLine(index, 'unit_cost', event.target.value)}/></label>
        <button type="button" className="catalog-icon-button purchase-remove-line" aria-label="Remove item" disabled={lines.length === 1} onClick={() => setLines((current) => current.filter((_, lineIndex) => lineIndex !== index))}><X size={15}/></button>
      </div>)}</div>
      <div className="catalog-form-row"><label className="catalog-field">Expected delivery<input type="date" value={expectedDelivery} onChange={(event) => setExpectedDelivery(event.target.value)}/></label><label className="catalog-field">Order notes<input maxLength={240} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Delivery instructions or internal notes"/></label></div>
      <div className="purchase-modal-total"><span>Order total</span><strong>{currency(total)}</strong></div>
      {error && <p className="catalog-form-error">{error}</p>}
      {!suppliers.length && <p className="catalog-form-error">Add a supplier before creating a purchase order.</p>}
      {!products.length && <p className="catalog-form-error">Add products before creating a purchase order.</p>}
      <div className="catalog-modal-actions"><button type="button" className="catalog-button catalog-button-light" onClick={onClose}>Cancel</button><button className="catalog-button catalog-button-primary" disabled={saving || !suppliers.length || !products.length}>{saving ? 'Creating…' : 'Create purchase order'}</button></div>
    </form>
  </div>;
}

function PurchaseStockAdjustment({ products, onClose, onSaved }: {
  products: Product[];
  onClose: () => void;
  onSaved: (product: Product, delta: number) => Promise<void>;
}) {
  const [productId, setProductId] = useState('');
  const [adjustmentType, setAdjustmentType] = useState<Extract<InventoryAdjustment['adjustment_type'], 'increase' | 'decrease'>>('increase');
  const [quantity, setQuantity] = useState('1');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const selectedProduct = products.find((product) => product.id === Number(productId));
  const quantityValue = Number(quantity);
  const delta = adjustmentType === 'increase' ? quantityValue : -quantityValue;
  const isValidQuantity = Number.isInteger(quantityValue) && quantityValue > 0;

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProduct) { setError('Select a product from the product dashboard.'); return; }
    if (!isValidQuantity) { setError('Enter a whole number greater than zero.'); return; }
    if (adjustmentType === 'decrease' && quantityValue > selectedProduct.quantity) {
      setError(`Cannot remove more than the current stock of ${selectedProduct.quantity} units.`);
      return;
    }
    setSaving(true);
    setError('');
    try {
      await api.adjustInventory({
        product: selectedProduct.id,
        adjustment_type: adjustmentType,
        quantity: quantityValue,
        reason: 'Purchase dashboard stock adjustment',
      });
      await onSaved(selectedProduct, delta);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not adjust product stock.');
    } finally {
      setSaving(false);
    }
  }

  return <div className="catalog-overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <form className="catalog-modal purchase-payment-modal" onSubmit={submit}>
      <div className="catalog-modal-heading"><div><span className="catalog-eyebrow">PRODUCT INVENTORY</span><h2>Adjust product stock</h2><p>Stock changes immediately and are recorded in inventory history.</p></div><button className="catalog-icon-button" type="button" onClick={onClose} aria-label="Close"><X size={18}/></button></div>
      <label className="catalog-field">Product from product dashboard<select required value={productId} onChange={(event) => setProductId(event.target.value)}><option value="">Select a product</option>{products.map((product) => <option key={product.id} value={product.id}>{product.name} · {product.sku} · ID {product.id}</option>)}</select></label>
      {selectedProduct && <p className="purchase-payment-confirmation">Product ID {selectedProduct.id} · Current stock: {selectedProduct.quantity} units</p>}
      <label className="catalog-field">Adjustment<select value={adjustmentType} onChange={(event) => setAdjustmentType(event.target.value as typeof adjustmentType)}><option value="increase">Increase stock</option><option value="decrease">Decrease stock</option></select></label>
      <label className="catalog-field">Units to {adjustmentType === 'increase' ? 'add' : 'remove'}<input type="number" min="1" step="1" required value={quantity} onChange={(event) => setQuantity(event.target.value)}/></label>
      {selectedProduct && <p className="purchase-payment-confirmation">New stock: {Math.max(0, selectedProduct.quantity + (isValidQuantity ? delta : 0))} units</p>}
      {error && <p className="catalog-form-error">{error}</p>}
      {!products.length && <p className="catalog-form-error">Add a product before adjusting stock.</p>}
      <div className="catalog-modal-actions"><button type="button" className="catalog-button catalog-button-light" onClick={onClose}>Cancel</button><button className="catalog-button catalog-button-primary" disabled={saving || !selectedProduct || !isValidQuantity || (adjustmentType === 'decrease' && quantityValue > (selectedProduct?.quantity ?? 0))}>{saving ? 'Updating…' : 'Update stock'}</button></div>
    </form>
  </div>;
}

function PurchasePaymentForm({ purchase, onClose, onSaved }: {
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
    <form className="catalog-modal purchase-payment-modal" onSubmit={submit}>
      <div className="catalog-modal-heading"><div><span className="catalog-eyebrow">SUPPLIER PAYMENT</span><h2>Confirm payment</h2><p>Record how much the supplier has received for {purchase.reference}.</p></div><button className="catalog-icon-button" type="button" onClick={onClose} aria-label="Close"><X size={18}/></button></div>
      <div className="purchase-payment-summary">
        <div><span>ORDER TOTAL</span><strong>{currency(purchase.total)}</strong></div>
        <div><span>ALREADY PAID</span><strong>{currency(purchase.paid_amount)}</strong></div>
        <div><span>REMAINING</span><strong>{currency(purchase.remaining_balance)}</strong></div>
      </div>
      <div className="purchase-payment-presets">
        <button type="button" className="catalog-button catalog-button-light" onClick={() => setAmount((remaining / 2).toFixed(2))}>Half of remaining</button>
        <button type="button" className="catalog-button catalog-button-light" onClick={() => setAmount(purchase.remaining_balance)}>Pay in full</button>
      </div>
      <label className="catalog-field">Amount paid<input type="number" min="0.01" max={purchase.remaining_balance} step="0.01" required value={amount} onChange={(event) => setAmount(event.target.value)}/></label>
      <label className="catalog-field">Payment method<select required value={paymentMethod} onChange={(event) => setPaymentMethod(event.target.value as typeof paymentMethod)}><option value="" disabled>Select a payment method</option><option value="cash">Cash</option><option value="mobile">Mobile money</option><option value="card">Card</option><option value="transfer">Bank transfer</option><option value="check">Check</option></select></label>
      <label className="catalog-field">Payment reference <span className="purchase-payment-optional">(optional)</span><input maxLength={80} value={reference} onChange={(event) => setReference(event.target.value)} placeholder="Receipt, transfer, or transaction number"/></label>
      <p className="purchase-payment-confirmation">Confirming records this payment and reduces the supplier’s outstanding account balance.</p>
      {error && <p className="catalog-form-error">{error}</p>}
      <div className="catalog-modal-actions"><button type="button" className="catalog-button catalog-button-light" onClick={onClose}>Cancel</button><button className="catalog-button catalog-button-primary" disabled={saving}>{saving ? 'Recording…' : 'Confirm payment'}</button></div>
    </form>
  </div>;
}

export default function PurchasesDashboard({ initialSupplierId = null, onInitialSupplierUsed, onOpenInventory, onOpenProducts }: {
  initialSupplierId?: number | null;
  onInitialSupplierUsed?: () => void;
  onOpenInventory: () => void;
  onOpenProducts: () => void;
}) {
  const dataRevision = useDataRevision();
  const [preselectedSupplierId] = useState(initialSupplierId);
  const [purchases, setPurchases] = useState<Purchase[]>([]);
  const [summary, setSummary] = useState<PurchaseSummary | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<PurchaseStatusFilter>('All orders');
  const [historyRange, setHistoryRange] = useState<PurchaseHistoryRange>('1d');
  const [historyMonthMode, setHistoryMonthMode] = useState(false);
  const [historyDayMode, setHistoryDayMode] = useState(false);
  const [historyMonth, setHistoryMonth] = useState(currentMonth);
  const [historyDate, setHistoryDate] = useState(currentDate);
  const [showForm, setShowForm] = useState(false);
  const [showStockAdjustment, setShowStockAdjustment] = useState(false);
  const [busyPurchase, setBusyPurchase] = useState<number | null>(null);
  const [paymentPurchase, setPaymentPurchase] = useState<Purchase | null>(null);
  const [notice, setNotice] = useState('');

  async function loadData() {
    setLoading(true);
    setError('');
    try {
      const [purchaseRows, summaryRow, productRows, supplierRows] = await Promise.all([
        api.purchases(), api.purchaseSummary(), api.products(), api.suppliers(),
      ]);
      setPurchases(purchaseRows);
      setSummary(summaryRow);
      setProducts(productRows);
      setSuppliers(supplierRows);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The purchases service could not be reached.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadData(); }, [dataRevision]);
  useEffect(() => {
    if (!initialSupplierId) return;
    setShowForm(true);
    onInitialSupplierUsed?.();
  }, []);

  const filteredPurchases = useMemo(() => {
    const term = query.trim().toLowerCase();
    const now = Date.now();
    const rangeStart = now - daysForPurchaseRange(historyRange) * 24 * 60 * 60 * 1000;
    const [selectedYear, selectedMonth] = historyMonth.split('-').map(Number);
    return purchases.filter((purchase) => {
      const matchesTerm = !term || `${purchase.reference} ${purchase.supplier_name} ${purchase.items.map((item) => `${item.product_name} ${item.product_sku}`).join(' ')}`.toLowerCase().includes(term);
      const matchesStatus = statusFilter === 'All orders' || purchase.status === statusFilter.toLowerCase();
      const orderedDate = new Date(purchase.ordered_at);
      const orderedAt = orderedDate.getTime();
      const matchesRange = historyDayMode
        ? Number.isFinite(orderedAt) && localDateValue(orderedDate) === historyDate
        : historyMonthMode
          ? Number.isFinite(orderedAt) && orderedDate.getFullYear() === selectedYear && orderedDate.getMonth() + 1 === selectedMonth
          : Number.isFinite(orderedAt) && orderedAt >= rangeStart && orderedAt <= now;
      return matchesTerm && matchesStatus && matchesRange;
    });
  }, [purchases, query, statusFilter, historyRange, historyMonthMode, historyMonth, historyDayMode, historyDate]);

  async function receive(purchase: Purchase) {
    setBusyPurchase(purchase.id);
    setError('');
    try {
      await api.receivePurchase(purchase.id);
      setNotice(`${purchase.reference} received and stock updated.`);
      await loadData();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not receive this purchase.');
    } finally {
      setBusyPurchase(null);
    }
  }

  async function saveStockAdjustment(product: Product, delta: number) {
    setShowStockAdjustment(false);
    await loadData();
    setNotice(`${product.name} (ID ${product.id}) stock ${delta > 0 ? 'increased' : 'decreased'} by ${Math.abs(delta)} units.`);
  }

  return <>
    <section className="catalog-heading purchase-heading"><div><div className="catalog-breadcrumb">Operations <span>›</span> <b>Purchases</b></div><h1>Purchases</h1><p>Manage supplier orders and receive stock into inventory.</p></div><div className="catalog-heading-actions"><button className="catalog-button catalog-button-light" onClick={onOpenProducts}><Package size={14}/>Products</button><button className="catalog-button catalog-button-light" onClick={onOpenInventory}><Truck size={14}/>Inventory</button><button className="catalog-button catalog-button-light" onClick={() => setShowStockAdjustment(true)} disabled={!products.length}><Plus size={15}/>Adjust stock</button><button className="catalog-button catalog-button-primary" onClick={() => setShowForm(true)}><Plus size={15}/>New purchase</button></div></section>
    {!loading && !error && summary && <section className="overview-metrics purchase-metrics" aria-label="Purchase metrics">
      <article><span>OPEN ORDERS</span><strong>{summary.open_orders.toLocaleString()}</strong><small><FileText size={13}/> Awaiting delivery</small></article>
      <article><span>OPEN ORDER VALUE</span><strong>{currency(summary.open_value)}</strong><small><Truck size={13}/> Supplier commitments</small></article>
      <article><span>RECEIVED THIS MONTH</span><strong>{summary.received_this_month.toLocaleString()}</strong><small><Check size={13}/> Completed orders</small></article>
      <article><span>SPEND THIS MONTH</span><strong>{currency(summary.spent_this_month)}</strong><small><ArrowDownToLine size={13}/> Received purchase value</small></article>
    </section>}
    {loading && <section className="overview-state">Loading purchase orders…</section>}
    {!loading && error && <section className="overview-state overview-error"><strong>Could not load purchases</strong><span>{error}</span><button className="catalog-button catalog-button-light" onClick={() => void loadData()}><RefreshCw size={14}/>Retry</button></section>}
    {!loading && !error && <>
      <section className="catalog-filter-panel purchase-filters"><div className="catalog-filter-row"><label className="catalog-search product-search"><Search size={15}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search orders, suppliers, products"/><kbd>/</kbd></label><label className="catalog-select"><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as PurchaseStatusFilter)}><option>All orders</option><option>Ordered</option><option>Received</option><option>Cancelled</option></select><ChevronDown size={13}/></label><div className="overview-flow-controls"><label className="catalog-select"><select aria-label="Purchase history range" value={historyDayMode ? 'day' : historyMonthMode ? 'month' : historyRange} onChange={(event) => { if (event.target.value === 'day') { setHistoryDayMode(true); setHistoryMonthMode(false); } else if (event.target.value === 'month') { setHistoryMonthMode(true); setHistoryDayMode(false); } else { setHistoryMonthMode(false); setHistoryDayMode(false); setHistoryRange(event.target.value as PurchaseHistoryRange); } }}><optgroup label="Rolling history">{PURCHASE_HISTORY_RANGES.map((range) => <option key={range.value} value={range.value}>{range.label}</option>)}</optgroup><option value="day">Choose a day</option><option value="month">Choose month &amp; year</option></select><ChevronDown size={13}/></label>{historyDayMode && <input className="overview-flow-month-picker" type="date" aria-label="Select purchase history day" value={historyDate} onChange={(event) => setHistoryDate(event.target.value)}/>}{historyMonthMode && <input className="overview-flow-month-picker" type="month" aria-label="Select purchase history month and year" value={historyMonth} onChange={(event) => setHistoryMonth(event.target.value)}/>}</div><span className="inventory-result-count">{filteredPurchases.length} orders</span></div></section>
      {error && <section className="purchase-inline-error"><CircleAlert size={14}/>{error}</section>}
      {notice && <div className="catalog-toast"><Check size={15}/>{notice}<button onClick={() => setNotice('')} aria-label="Dismiss"><X size={14}/></button></div>}
      <section className="catalog-table-panel purchase-table-panel"><div className="catalog-table-scroll"><table className="catalog-table purchase-table"><thead><tr><th>ORDER</th><th>SUPPLIER</th><th>ITEMS</th><th>ORDERED</th><th>TOTAL</th><th>PAID</th><th>REMAINING</th><th>PAYMENT</th><th>STATUS</th><th aria-label="Actions"/></tr></thead><tbody>
        {filteredPurchases.map((purchase) => <tr key={purchase.id}>
          <td><strong className="purchase-reference">{purchase.reference}</strong><small className="purchase-first-item">{purchase.items.slice(0, 2).map((item) => item.product_name).join(', ')}{purchase.items.length > 2 ? ` +${purchase.items.length - 2} more` : ''}</small></td>
          <td>{purchase.supplier_name}</td><td>{purchase.item_count.toLocaleString()} units</td><td>{dateLabel(purchase.ordered_at)}</td><td><strong>{currency(purchase.total)}</strong></td>
          <td>{currency(purchase.paid_amount)}</td><td><strong>{currency(purchase.remaining_balance)}</strong></td>
          <td><span className={`purchase-payment-status ${purchase.payment_status}`}>{purchase.payment_status === 'not_due' ? 'Not due' : purchase.payment_status}</span></td>
          <td><span className={`purchase-status ${purchase.status}`}>{purchase.status}</span></td>
          <td>{purchase.status === 'ordered' ? <button className="catalog-button catalog-button-light purchase-receive-button" disabled={busyPurchase === purchase.id} onClick={() => void receive(purchase)}>{busyPurchase === purchase.id ? 'Receiving…' : 'Receive order'}</button> : purchase.payment_status !== 'paid' && purchase.status === 'received' ? <button className="catalog-button catalog-button-light purchase-receive-button" onClick={() => setPaymentPurchase(purchase)}>Record payment</button> : <span className="catalog-muted">{purchase.payment_status === 'paid' ? 'Paid in full' : '—'}</span>}</td>
        </tr>)}
        {!filteredPurchases.length && <tr><td colSpan={10} className="catalog-state">No purchase orders match your filters. Create an order to get started.</td></tr>}
      </tbody></table></div><footer className="catalog-table-footer"><span>Showing <b>{filteredPurchases.length}</b> of <b>{purchases.length}</b> purchase orders</span><button className="catalog-clear" onClick={() => { setQuery(''); setStatusFilter('All orders'); setHistoryRange('1d'); setHistoryMonthMode(false); setHistoryDayMode(false); setHistoryMonth(currentMonth()); setHistoryDate(currentDate()); }}>Clear filters</button></footer></section>
    </>}
    {showForm && <PurchaseForm products={products} suppliers={suppliers} initialSupplierId={preselectedSupplierId} onClose={() => setShowForm(false)} onSaved={async () => { setShowForm(false); await loadData(); setNotice('Purchase order created. Stock will update when it is received.'); }}/>}
    {showStockAdjustment && <PurchaseStockAdjustment products={products} onClose={() => setShowStockAdjustment(false)} onSaved={saveStockAdjustment}/>}
    {paymentPurchase && <PurchasePaymentForm purchase={paymentPurchase} onClose={() => setPaymentPurchase(null)} onSaved={async () => { const reference = paymentPurchase.reference; setPaymentPurchase(null); await loadData(); setNotice(`Payment recorded for ${reference}.`); }}/>}
  </>;
}
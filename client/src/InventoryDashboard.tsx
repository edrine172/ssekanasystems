import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, ChevronDown, ClipboardCheck, Package, Plus, RefreshCw, Search, Truck, Warehouse, X } from 'lucide-react';
import { api, formatCurrency as currency, type DashboardSummary, type InventoryAdjustment, type Product, type StockMovement } from './api';
import { useDataRevision } from './dataSync';

type AdjustmentType = InventoryAdjustment['adjustment_type'];
type StockFilter = 'All stock' | 'In stock' | 'Low stock' | 'Out of stock';
type InventoryHistoryEntry = {
  id: string;
  product_name: string;
  product_sku: string;
  movement_type: StockMovement['movement_type'] | 'client_receipt';
  quantity: number;
  note: string;
  reference: string;
  created_at: string;
};
const AUDIT_RANGES = [
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
type AuditRange = typeof AUDIT_RANGES[number]['value'];
const daysForAuditRange = (range: AuditRange) => AUDIT_RANGES.find((option) => option.value === range)!.days;
const currentMonth = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
};
const statusFor = (product: Product): Exclude<StockFilter, 'All stock'> => product.quantity === 0 ? 'Out of stock' : product.quantity <= product.reorder_level ? 'Low stock' : 'In stock';

function StockAdjustmentForm({ product, products, onClose, onSaved }: {
  product: Product | null;
  products: Product[];
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const initialProduct = product?.id ?? products[0]?.id;
  const [productId, setProductId] = useState(String(initialProduct ?? ''));
  const [adjustmentType, setAdjustmentType] = useState<AdjustmentType>('decrease');
  const [quantity, setQuantity] = useState('1');
  const [countedQuantity, setCountedQuantity] = useState(String(product?.quantity ?? 0));
  const [reason, setReason] = useState('Cycle count');
  const [reference, setReference] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const selectedProduct = products.find((item) => item.id === Number(productId));
  const nextProductQuantity = adjustmentType === 'count'
    ? Number(countedQuantity)
    : (selectedProduct?.quantity ?? 0) + (adjustmentType === 'increase' ? 1 : -1) * Number(quantity || 0);
  const delta = nextProductQuantity - (selectedProduct?.quantity ?? 0);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProduct) { setError('Select a product before adjusting stock.'); return; }
    setSaving(true);
    setError('');
    const payload: InventoryAdjustment = {
      product: selectedProduct.id,
      adjustment_type: adjustmentType,
      reason,
      reference: reference.trim(),
      notes: notes.trim(),
      ...(adjustmentType === 'count' ? { counted_quantity: Number(countedQuantity) } : { quantity: Number(quantity) }),
    };
    try {
      await api.adjustInventory(payload);
      await onSaved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not apply this adjustment.');
    } finally {
      setSaving(false);
    }
  }

  return <div className="catalog-overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <form className="catalog-modal inventory-adjustment-modal" onSubmit={submit}>
      <div className="catalog-modal-heading"><div><span className="catalog-eyebrow">INVENTORY CONTROL</span><h2>Adjust stock quantity</h2><p>Changes are recorded in the stock movement audit trail.</p></div><button className="catalog-icon-button" type="button" onClick={onClose} aria-label="Close"><X size={18}/></button></div>
      <label className="catalog-field">Product &amp; SKU<select required value={productId} onChange={(event) => { setProductId(event.target.value); const chosen = products.find((item) => item.id === Number(event.target.value)); setCountedQuantity(String(chosen?.quantity ?? 0)); }}><option value="">Select a product</option>{products.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.sku} · {item.quantity} units</option>)}</select></label>
      <fieldset className="inventory-adjustment-types"><legend>Adjustment type</legend>{([['increase', 'Increase (found)'], ['decrease', 'Decrease'], ['damage', 'Damage'], ['loss', 'Loss / theft'], ['count', 'Inventory count']] as [AdjustmentType, string][]).map(([value, label]) => <label key={value} className={adjustmentType === value ? 'selected' : ''}><input type="radio" name="adjustment-type" value={value} checked={adjustmentType === value} onChange={() => setAdjustmentType(value)}/>{label}</label>)}</fieldset>
      {adjustmentType === 'count' ? <label className="catalog-field">Counted quantity<input type="number" min="0" step="1" required value={countedQuantity} onChange={(event) => setCountedQuantity(event.target.value)}/></label> : <label className="catalog-field">Units to {adjustmentType === 'increase' ? 'add' : 'deduct'}<input type="number" min="1" step="1" required value={quantity} onChange={(event) => setQuantity(event.target.value)}/></label>}
      <div className={`inventory-adjustment-forecast ${nextProductQuantity < 0 ? 'forecast-error' : ''}`}><span>Current stock <strong>{selectedProduct?.quantity ?? 0}</strong></span><b aria-hidden="true">→</b><span>New stock <strong>{Math.max(nextProductQuantity, 0)}</strong></span><small>{selectedProduct?.location || 'No storage location assigned'}{delta ? ` · ${delta > 0 ? '+' : ''}${delta} units` : ''}</small></div>
      <div className="catalog-form-row"><label className="catalog-field">Reason<select value={reason} onChange={(event) => setReason(event.target.value)}><option>Cycle count</option><option>Found stock</option><option>Damaged during handling</option><option>Loss / theft</option><option>Data correction</option><option>Other</option></select></label><label className="catalog-field">Reference<input maxLength={80} value={reference} onChange={(event) => setReference(event.target.value)} placeholder="Ticket, batch, or document"/></label></div>
      <label className="catalog-field">Audit notes<textarea maxLength={158} rows={3} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Add context for this stock change"/></label>
      {error && <p className="catalog-form-error">{error}</p>}
      <div className="catalog-modal-actions"><button type="button" className="catalog-button catalog-button-light" onClick={onClose}>Cancel</button><button className="catalog-button catalog-button-primary" disabled={saving || !selectedProduct || delta === 0 || nextProductQuantity < 0}>{saving ? 'Applying…' : 'Confirm adjustment'}</button></div>
    </form>
  </div>;
}

export default function InventoryDashboard({ onOpenProducts, onOpenPurchases, onInventoryChanged }: {
  onOpenProducts: () => void;
  onOpenPurchases: () => void;
  onInventoryChanged: () => Promise<void>;
}) {
  const dataRevision = useDataRevision();
  const [products, setProducts] = useState<Product[]>([]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [auditMovements, setAuditMovements] = useState<InventoryHistoryEntry[]>([]);
  const [auditRange, setAuditRange] = useState<AuditRange>('1d');
  const [auditMonthMode, setAuditMonthMode] = useState(false);
  const [auditMonth, setAuditMonth] = useState(currentMonth);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState('');
  const auditRequest = useRef(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [stockFilter, setStockFilter] = useState<StockFilter>('All stock');
  const [categoryFilter, setCategoryFilter] = useState('All categories');
  const [adjustingProduct, setAdjustingProduct] = useState<Product | null | undefined>(undefined);

  async function loadAuditHistory(range: AuditRange = auditRange, month?: string) {
    const requestId = ++auditRequest.current;
    setAuditLoading(true);
    setAuditError('');
    try {
      const [movementRows, materialOrders] = await Promise.all([
        api.movements(month ? undefined : daysForAuditRange(range), month),
        api.clientMaterialOrders(),
      ]);
      if (requestId === auditRequest.current) {
        const rangeStart = new Date();
        rangeStart.setHours(0, 0, 0, 0);
        rangeStart.setDate(rangeStart.getDate() - daysForAuditRange(range) + 1);
        const materialReceipts = materialOrders.flatMap((order) => order.receipts
          .filter((receipt) => month
            ? receipt.received_at.slice(0, 7) === month
            : new Date(receipt.received_at).getTime() >= rangeStart.getTime())
          .map((receipt) => ({
            id: `client-receipt-${receipt.id}`,
            product_name: order.material_name,
            product_sku: order.reference,
            movement_type: 'client_receipt' as const,
            quantity: Number(receipt.quantity),
            note: `Client-supplied stock received from ${order.customer_name}`,
            reference: receipt.reference,
            created_at: receipt.received_at,
          })));
        const stockMovements = movementRows.map((movement) => ({
          ...movement,
          id: `stock-movement-${movement.id}`,
        }));
        setAuditMovements(
          [...stockMovements, ...materialReceipts]
            .sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime()),
        );
      }
    } catch (cause) {
      if (requestId === auditRequest.current) setAuditError(cause instanceof Error ? cause.message : 'Audit history could not be loaded.');
    } finally {
      if (requestId === auditRequest.current) setAuditLoading(false);
    }
  }

  async function loadData() {
    setLoading(true);
    setError('');
    try {
      const [productRows, summaryRow] = await Promise.all([api.products(), api.summary()]);
      setProducts(productRows);
      setSummary(summaryRow);
      await loadAuditHistory(auditRange);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The inventory service could not be reached.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadData(); }, [dataRevision]);

  const categories = useMemo(() => [...new Set(products.map((product) => product.category_name).filter(Boolean))].sort(), [products]);
  const filteredProducts = useMemo(() => {
    const term = query.trim().toLowerCase();
    return products.filter((product) => {
      const matchesTerm = !term || `${product.name} ${product.sku} ${product.location} ${product.category_name}`.toLowerCase().includes(term);
      const matchesStatus = stockFilter === 'All stock' || statusFor(product) === stockFilter;
      const matchesCategory = categoryFilter === 'All categories' || product.category_name === categoryFilter;
      return matchesTerm && matchesStatus && matchesCategory;
    }).sort((a, b) => a.quantity - b.quantity || a.name.localeCompare(b.name));
  }, [products, query, stockFilter, categoryFilter]);
  const recentMovements = auditMovements;
  const movementDelta = (movement: InventoryHistoryEntry) => {
    if (movement.movement_type === 'outbound') return -Math.abs(movement.quantity);
    if (movement.movement_type === 'inbound' || movement.movement_type === 'return' || movement.movement_type === 'client_receipt') {
      return Math.abs(movement.quantity);
    }
    return movement.quantity;
  };
  const movementLabel = (movement: InventoryHistoryEntry) => ({
    inbound: 'Purchase received',
    outbound: 'Customer delivery',
    adjustment: 'Stock adjustment',
    return: 'Stock returned',
    client_receipt: 'Client-supplied stock received',
  })[movement.movement_type];

  return <>
    <section className="catalog-heading inventory-heading"><div><div className="catalog-breadcrumb">Operations <span>›</span> <b>Inventory</b></div><h1>Inventory Management</h1><p>Monitor stock levels, identify replenishment needs, and record audited adjustments.</p></div><div className="catalog-heading-actions"><button className="catalog-button catalog-button-light" onClick={onOpenProducts}><Package size={14}/>Products</button><button className="catalog-button catalog-button-light" onClick={onOpenPurchases}><Truck size={14}/>Purchases</button><button className="catalog-button catalog-button-primary" onClick={() => setAdjustingProduct(null)} disabled={!products.length}><Plus size={15}/>Adjust stock</button></div></section>
    {!loading && !error && summary && <section className="overview-metrics inventory-metrics" aria-label="Inventory metrics">
      <article><span>TOTAL UNITS</span><strong>{summary.total_units.toLocaleString()}</strong><small><Warehouse size={13}/> Across {summary.total_skus.toLocaleString()} SKUs</small></article>
      <article><span>INVENTORY VALUE</span><strong>{currency(summary.inventory_value)}</strong><small><ClipboardCheck size={13}/> Valued at cost</small></article>
      <article className="overview-alert-metric"><span>LOW STOCK</span><strong>{summary.low_stock_count.toLocaleString()}</strong><small><AlertTriangle size={13}/> At or below reorder point</small></article>
      <article className="overview-alert-metric"><span>OUT OF STOCK</span><strong>{summary.out_of_stock_count.toLocaleString()}</strong><small><AlertTriangle size={13}/> Replenishment required</small></article>
    </section>}
    {loading && <section className="overview-state">Loading inventory from the API…</section>}
    {!loading && error && <section className="overview-state overview-error"><strong>Could not load inventory</strong><span>{error}</span><button className="catalog-button catalog-button-light" onClick={() => void loadData()}><RefreshCw size={14}/>Retry</button></section>}
    {!loading && !error && <>
      <section className="catalog-filter-panel inventory-filters"><div className="catalog-filter-row"><label className="catalog-search product-search"><Search size={15}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search product, SKU, or location"/><kbd>/</kbd></label><label className="catalog-select"><select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}><option>All categories</option>{categories.map((category) => <option key={category}>{category}</option>)}</select><ChevronDown size={13}/></label><label className="catalog-select"><select value={stockFilter} onChange={(event) => setStockFilter(event.target.value as StockFilter)}><option>All stock</option><option>In stock</option><option>Low stock</option><option>Out of stock</option></select><ChevronDown size={13}/></label><span className="inventory-result-count">{filteredProducts.length} products</span></div></section>
      <section className="catalog-table-panel inventory-table-panel"><div className="catalog-table-scroll"><table className="catalog-table inventory-table"><thead><tr><th>PRODUCT / SKU</th><th>CATEGORY</th><th>LOCATION</th><th>ON HAND</th><th>REORDER AT</th><th>STATUS</th><th>UPDATED</th><th aria-label="Actions"/></tr></thead><tbody>
        {filteredProducts.map((product) => {
          const status = statusFor(product);
          return <tr key={product.id}><td><div className="catalog-product-cell"><span className="catalog-product-thumb"><Package size={17}/></span><span><strong>{product.name}</strong><small>{product.sku}</small></span></div></td><td>{product.category_name}</td><td>{product.location || <span className="catalog-muted">Unassigned</span>}</td><td><strong className={`catalog-quantity ${status === 'Out of stock' ? 'is-out' : status === 'Low stock' ? 'is-low' : ''}`}>{product.quantity.toLocaleString()}</strong></td><td>{product.reorder_level.toLocaleString()} units</td><td><span className={`catalog-status ${status.toLowerCase().replace(/ /g, '-')}`}>{status}</span></td><td>{new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' }).format(new Date(product.updated_at))}</td><td><button className="catalog-row-action inventory-adjust-button" aria-label={`Adjust ${product.name}`} onClick={() => setAdjustingProduct(product)}><Plus size={15}/></button></td></tr>;
        })}
        {!filteredProducts.length && <tr><td colSpan={8} className="catalog-state">No products match this search or stock filter.</td></tr>}
      </tbody></table></div><footer className="catalog-table-footer"><span>Showing <b>{filteredProducts.length}</b> of <b>{products.length}</b> products</span><button className="catalog-clear" onClick={() => { setQuery(''); setStockFilter('All stock'); setCategoryFilter('All categories'); }}>Clear filters</button></footer></section>
      <section className="overview-panel overview-activity-panel inventory-audit-panel"><div className="overview-panel-heading"><div><span>INVENTORY HISTORY</span><h2>Stock movement history</h2></div><div className="overview-flow-controls"><label className="catalog-select inventory-audit-range"><select aria-label="Inventory history range" value={auditMonthMode ? 'month' : auditRange} onChange={(event) => { if (event.target.value === 'month') { setAuditMonthMode(true); void loadAuditHistory(auditRange, auditMonth); } else { const range = event.target.value as AuditRange; setAuditMonthMode(false); setAuditRange(range); void loadAuditHistory(range); } }}><optgroup label="Rolling history">{AUDIT_RANGES.map((range) => <option key={range.value} value={range.value}>{range.label}</option>)}</optgroup><option value="month">Choose month &amp; year</option></select><ChevronDown size={13}/></label>{auditMonthMode && <input className="overview-flow-month-picker" type="month" aria-label="Select inventory history month and year" value={auditMonth} onChange={(event) => { setAuditMonth(event.target.value); if (event.target.value) void loadAuditHistory(auditRange, event.target.value); }}/>}</div></div>{auditLoading ? <p className="overview-empty">Loading inventory history…</p> : auditError ? <div className="overview-empty">{auditError} <button className="catalog-button catalog-button-light" onClick={() => void loadAuditHistory(auditRange, auditMonthMode ? auditMonth : undefined)}>Retry</button></div> : recentMovements.length ? <div className="overview-activity-list">{recentMovements.map((movement) => { const delta = movementDelta(movement); return <div className="overview-activity-row" key={movement.id}><span className="overview-movement-icon"><ClipboardCheck size={14}/></span><span className="overview-activity-copy"><strong>{movement.product_name} · {movement.product_sku}</strong><small>{movementLabel(movement)} · {movement.note || 'Inventory updated'}{movement.reference ? ` · ${movement.reference}` : ''}</small></span><span className={`overview-movement-quantity ${delta > 0 ? 'is-inbound' : ''}`}>{delta > 0 ? '+' : ''}{delta}</span><time>{new Intl.DateTimeFormat('en-US', { year: 'numeric', month: 'short', day: 'numeric' }).format(new Date(movement.created_at))}</time></div>; })}</div> : <p className="overview-empty">No stock movements in the selected period.</p>}</section>
    </>}
    {adjustingProduct !== undefined && <StockAdjustmentForm key={adjustingProduct?.id ?? 'new'} product={adjustingProduct} products={products} onClose={() => setAdjustingProduct(undefined)} onSaved={async () => { setAdjustingProduct(undefined); await loadData(); await onInventoryChanged(); }}/ >}
  </>;
}
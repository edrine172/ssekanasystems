import { useEffect, useMemo, useRef, useState } from 'react';
import { Banknote, Barcode, BriefcaseBusiness, Check, CreditCard, Minus, Package, Plus, Printer, Search, Smartphone, Tag, Truck, Users, Wallet, X } from 'lucide-react';
import { api, formatCurrency as currency, type Customer, type Product, type Sale, type SalesSummary } from './api';
import { useDataRevision } from './dataSync';

type PaymentMethod = Sale['payment_method'];
type CartLine = { product: Product; quantity: number; unitPrice: string };
type HeldCart = { id: number; customer: string; customerId: number | null; lines: CartLine[]; discountPercent: number; savedAt: number };
const TAX_RATE = 0;
const paymentMethods: Array<{ value: PaymentMethod; label: string; icon: typeof Banknote }> = [
  { value: 'cash', label: 'Cash', icon: Banknote },
  { value: 'card', label: 'Card', icon: CreditCard },
  { value: 'mobile', label: 'Mobile', icon: Smartphone },
  { value: 'transfer', label: 'Transfer', icon: Wallet },
  { value: 'account', label: 'Account', icon: BriefcaseBusiness },
];

export default function PosDashboard({ initialCustomerId, onOpenProducts, onOpenInventory, onSaleCompleted }: {
  initialCustomerId: number | null;
  onOpenProducts: () => void;
  onOpenInventory: () => void;
  onSaleCompleted: () => Promise<void>;
}) {
  const dataRevision = useDataRevision();
  const [products, setProducts] = useState<Product[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [salesSummary, setSalesSummary] = useState<SalesSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [activeCategory, setActiveCategory] = useState('All items');
  const [cart, setCart] = useState<CartLine[]>([]);
  const [quantityDrafts, setQuantityDrafts] = useState<Record<number, string>>({});
  const [customer, setCustomer] = useState('Walk-in Customer');
  const [customerId, setCustomerId] = useState<number | null>(null);
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>('cash');
  const [discountPercent, setDiscountPercent] = useState(0);
  const [cashTendered, setCashTendered] = useState('');
  const [saving, setSaving] = useState(false);
  const [receipt, setReceipt] = useState<Sale | null>(null);
  const [heldCarts, setHeldCarts] = useState<HeldCart[]>(() => {
    try { return JSON.parse(localStorage.getItem('stockpulse-held-carts') ?? '[]') as HeldCart[]; }
    catch { return []; }
  });
  const [notice, setNotice] = useState('');
  const scannerRef = useRef<HTMLInputElement>(null);
  const initialCustomerApplied = useRef(false);

  async function loadData() {
    setLoading(true);
    setError('');
    try {
      const [productRows, summary, customerRows] = await Promise.all([api.products(), api.salesSummary(), api.customers()]);
      setProducts(productRows);
      setSalesSummary(summary);
      setCustomers(customerRows);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The point-of-sale service could not be reached.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadData(); }, [dataRevision]);
  useEffect(() => { localStorage.setItem('stockpulse-held-carts', JSON.stringify(heldCarts)); }, [heldCarts]);
  useEffect(() => {
    if (!initialCustomerId || !customers.length || initialCustomerApplied.current) return;
    const selected = customers.find((item) => item.id === initialCustomerId);
    if (selected) {
      setCustomerId(selected.id);
      setCustomer(selected.name);
      initialCustomerApplied.current = true;
    }
  }, [initialCustomerId, customers]);

  const categories = useMemo(() => [...new Set(products.map((product) => product.category_name).filter(Boolean))], [products]);
  const visibleProducts = useMemo(() => {
    const term = search.trim().toLowerCase();
    return products.filter((product) => product.is_active && product.quantity > 0 && (activeCategory === 'All items' || product.category_name === activeCategory) && (!term || `${product.name} ${product.sku} ${product.category_name}`.toLowerCase().includes(term)));
  }, [products, activeCategory, search]);
  const subtotal = cart.reduce((sum, line) => sum + (Number(line.unitPrice || line.product.unit_price) || 0) * line.quantity, 0);
  const discountAmount = Math.round(subtotal * discountPercent) / 100;
  const selectedCustomer = customers.find((item) => item.id === customerId);
  const taxAmount = Math.round((subtotal - discountAmount) * TAX_RATE) / 100;
  const total = Math.round((subtotal - discountAmount + taxAmount) * 100) / 100;
  const availableCredit = selectedCustomer ? Math.max(0, Number(selectedCustomer.credit_limit) - Number(selectedCustomer.outstanding_balance)) : 0;
  const accountPaymentAllowed = Boolean(selectedCustomer?.is_active && availableCredit >= total && Number(selectedCustomer.credit_limit) > 0);
  const cashReceived = Number(cashTendered || 0);
  const cashRemaining = paymentMethod === 'cash' ? Math.max(0, Math.round((total - Math.min(cashReceived, total)) * 100) / 100) : 0;
  const changeDue = paymentMethod === 'cash' ? Math.max(0, Math.round((cashReceived - total) * 100) / 100) : 0;
  const partialPaymentAllowed = cashRemaining === 0 || Boolean(selectedCustomer?.is_active && Number(selectedCustomer.credit_limit) > 0 && availableCredit >= cashRemaining);
  const cartUnits = cart.reduce((sum, line) => sum + line.quantity, 0);
  const invalidUnitPrice = cart.some((line) => {
    const price = Number(line.unitPrice);
    return !line.unitPrice.trim() || !Number.isFinite(price) || price < 0 || Math.abs(price * 100 - Math.round(price * 100)) > 1e-7;
  });

  function addProduct(product: Product) {
    if (product.quantity < 1) return;
    setQuantityDrafts((current) => { const next = { ...current }; delete next[product.id]; return next; });
    setCart((current) => {
      const existing = current.find((line) => line.product.id === product.id);
      if (existing) return current.map((line) => line.product.id === product.id ? { ...line, quantity: Math.min(line.quantity + 1, product.quantity) } : line);
      return [...current, { product, quantity: 1, unitPrice: product.unit_price }];
    });
  }

  function changeUnitPrice(productId: number, unitPrice: string) {
    setCart((current) => current.map((line) => line.product.id === productId ? { ...line, unitPrice } : line));
  }

  function changeQuantity(productId: number, delta: number) {
    setQuantityDrafts((current) => { const next = { ...current }; delete next[productId]; return next; });
    setCart((current) => current.flatMap((line) => {
      if (line.product.id !== productId) return [line];
      const quantity = Math.min(line.product.quantity, line.quantity + delta);
      return quantity > 0 ? [{ ...line, quantity }] : [];
    }));
  }

  function commitQuantity(productId: number, rawValue: string) {
    const line = cart.find((item) => item.product.id === productId);
    setQuantityDrafts((current) => { const next = { ...current }; delete next[productId]; return next; });
    if (!line || line.product.quantity < 1) {
      setCart((current) => current.filter((item) => item.product.id !== productId));
      return;
    }
    const parsed = Math.floor(Number(rawValue));
    const quantity = Math.max(1, Math.min(Number.isFinite(parsed) ? parsed : 1, line.product.quantity));
    setCart((current) => current.map((item) => item.product.id === productId ? { ...item, quantity } : item));
  }

  function scanProduct(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key !== 'Enter') return;
    const product = products.find((item) => item.sku.toLowerCase() === search.trim().toLowerCase());
    if (product) { addProduct(product); setSearch(''); }
  }

  function holdCart() {
    if (!cart.length) return;
    setHeldCarts((current) => [{ id: Date.now(), customer, customerId, lines: cart, discountPercent, savedAt: Date.now() }, ...current].slice(0, 8));
    setCart([]);
    setCustomer('Walk-in Customer');
    setCustomerId(null);
    setDiscountPercent(0);
    setCashTendered('');
    setNotice('Cart held for later.');
  }

  function resumeCart(held: HeldCart) {
    setCart(held.lines.map((line) => ({ ...line, unitPrice: line.unitPrice ?? line.product.unit_price })));
    setCustomer(held.customer);
    setCustomerId(held.customerId ?? null);
    setDiscountPercent(held.discountPercent);
    setHeldCarts((current) => current.filter((item) => item.id !== held.id));
  }

  async function completeSale() {
    if (!cart.length || saving) return;
    setSaving(true);
    setError('');
    try {
      const sale = await api.checkoutSale({
        ...(customerId ? { customer: customerId } : {}),
        customer_name: customer.trim() || 'Walk-in Customer',
        payment_method: paymentMethod,
        discount_percent: discountPercent.toFixed(2),
        ...(paymentMethod === 'cash' ? { cash_tendered: cashReceived.toFixed(2) } : {}),
        items: cart.map((line) => ({
          product: line.product.id,
          quantity: line.quantity,
          unit_price: Number(line.unitPrice).toFixed(2),
        })),
      });
      setReceipt(sale);
      setCart([]);
      setDiscountPercent(0);
      setCashTendered('');
      await Promise.all([loadData(), onSaleCompleted()]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not complete this sale.');
    } finally {
      setSaving(false);
    }
  }

  return <>
    <section className="catalog-heading pos-heading"><div><div className="catalog-breadcrumb">Operations <span>›</span> <b>Point of sale</b></div><h1>Point of Sale</h1><p>Scan or select products, take payment, and update inventory at checkout.</p></div><div className="pos-live-status"><i/> Register ready <span>·</span> {salesSummary?.transactions_today ?? 0} sales today</div></section>
    {loading && <section className="overview-state">Loading register and inventory…</section>}
    {!loading && error && !products.length && <section className="overview-state overview-error"><strong>Could not load the register</strong><span>{error}</span><button className="catalog-button catalog-button-light" onClick={() => void loadData()}>Retry</button></section>}
    {!loading && !error && <div className="pos-workspace">
      <section className="pos-products-panel">
        <div className="pos-scanner-row"><label className="catalog-search pos-scanner"><Barcode size={16}/><input ref={scannerRef} value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={scanProduct} placeholder="Scan barcode or search SKU / product"/><kbd>ENTER</kbd></label><span className="pos-scanner-ready"><i/> Scanner ready</span></div>
        <div className="pos-category-tabs"><button className={activeCategory === 'All items' ? 'active' : ''} onClick={() => setActiveCategory('All items')}>All items <span>{products.filter((product) => product.quantity > 0).length}</span></button>{categories.map((category) => <button key={category} className={activeCategory === category ? 'active' : ''} onClick={() => setActiveCategory(category)}>{category} <span>{products.filter((product) => product.category_name === category && product.quantity > 0).length}</span></button>)}</div>
        <div className="pos-product-grid">{visibleProducts.map((product) => {
          const inCart = cart.find((line) => line.product.id === product.id)?.quantity ?? 0;
          return <article className="pos-product-card" key={product.id}>
            <div className={`pos-product-art pos-art-${product.id % 5}`}><Package size={25}/><span className={product.quantity <= product.reorder_level ? 'stock-low' : ''}><i/>{product.quantity} in stock</span></div>
            <div className="pos-product-info"><small>SKU: {product.sku}</small><strong>{product.name}</strong><div><b>{currency(product.unit_price)}</b><span>{product.category_name}</span></div></div>
            <button className="pos-add-button" onClick={() => addProduct(product)} disabled={inCart >= product.quantity}><Plus size={13}/>{inCart ? `Add another · ${inCart} in cart` : 'Add to cart'}</button>
          </article>;
        })}{!visibleProducts.length && <p className="pos-empty-products">No in-stock products match this search.</p>}</div>
        <div className="pos-product-footer"><span>Showing {visibleProducts.length} in-stock products</span><button className="catalog-clear" onClick={onOpenProducts}>Manage products <Package size={12}/></button></div>
      </section>

      <aside className="pos-cart-panel">
        <div className="pos-cart-heading"><div><span>ACTIVE CART</span><h2>Cart <small>{cartUnits} {cartUnits === 1 ? 'item' : 'items'}</small></h2></div><button className="catalog-clear pos-clear-cart" onClick={() => { setCart([]); setDiscountPercent(0); }} disabled={!cart.length}><X size={12}/>Clear</button></div>
        <label className="pos-customer-field"><Users size={14}/><select aria-label="Customer account" value={customerId ?? ''} onChange={(event) => { const id = event.target.value ? Number(event.target.value) : null; const selected = customers.find((item) => item.id === id); setCustomerId(id); setCustomer(selected?.name ?? 'Walk-in Customer'); if (paymentMethod === 'account' && !selected) setPaymentMethod('cash'); }}><option value="">Walk-in Customer</option>{customers.filter((item) => item.is_active).map((item) => <option key={item.id} value={item.id}>{item.name} · {item.customer_code}</option>)}</select></label>
        <div className="pos-cart-lines">{cart.map((line) => <div className="pos-cart-line" key={line.product.id}>
          <div className="pos-cart-line-title"><strong>{line.product.name}</strong><small>{line.product.sku}</small><button aria-label={`Remove ${line.product.name}`} onClick={() => setCart((current) => current.filter((item) => item.product.id !== line.product.id))}><X size={13}/></button></div>
          <div className="pos-cart-line-bottom"><div className="pos-quantity-control"><button aria-label={`Decrease ${line.product.name}`} onClick={() => changeQuantity(line.product.id, -1)}><Minus size={12}/></button><input aria-label={`Quantity for ${line.product.name}`} type="number" min="1" max={line.product.quantity} step="1" value={quantityDrafts[line.product.id] ?? String(line.quantity)} onChange={(event) => setQuantityDrafts((current) => ({ ...current, [line.product.id]: event.target.value }))} onBlur={(event) => commitQuantity(line.product.id, event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur(); }}/><button aria-label={`Increase ${line.product.name}`} onClick={() => changeQuantity(line.product.id, 1)} disabled={line.quantity >= line.product.quantity}><Plus size={12}/></button></div><label className="pos-unit-price">Unit price<input aria-label={`Unit price for ${line.product.name}`} type="number" min="0" step="0.01" value={line.unitPrice} onChange={(event) => changeUnitPrice(line.product.id, event.target.value)}/></label><strong>{currency((Number(line.unitPrice) || 0) * line.quantity)}</strong></div>
        </div>)}{!cart.length && <div className="pos-empty-cart"><Package size={21}/><strong>Your cart is empty</strong><span>Add products to start a sale.</span></div>}</div>
        <label className="pos-discount"><span><Tag size={13}/>Discount</span><span className="pos-percent-input"><input aria-label="Discount percent" type="number" min="0" max="100" step="1" value={discountPercent} onChange={(event) => setDiscountPercent(Math.max(0, Math.min(100, Number(event.target.value))))}/>%</span></label>
        <div className="pos-totals"><div><span>Subtotal · {cartUnits} items</span><strong>{currency(subtotal)}</strong></div><div><span>Discount</span><strong className="pos-discount-value">−{currency(discountAmount)}</strong></div><div><span>Tax after discount ({TAX_RATE}%)</span><strong>{currency(taxAmount)}</strong></div><div className="pos-grand-total"><span>Total</span><strong>{currency(total)}</strong></div></div>
        <div className="pos-payment-section"><span className="pos-section-label">PAYMENT METHOD</span><div className="pos-payment-methods">{paymentMethods.map(({ value, label, icon: Icon }) => <button key={value} className={paymentMethod === value ? 'active' : ''} onClick={() => setPaymentMethod(value)}><Icon size={14}/>{label}</button>)}</div>
          {paymentMethod === 'cash' && <div className="pos-cash-entry"><label>Amount received<input type="number" min="0.01" step="0.01" value={cashTendered} onChange={(event) => setCashTendered(event.target.value)} placeholder={total.toFixed(2)}/></label>{cashRemaining > 0 ? <><div className="pos-change-due pos-remaining-due"><span>Remaining amount</span><strong>{currency(cashRemaining)}</strong></div>{!selectedCustomer ? <small className="pos-error">Select a customer to place the remaining amount on their account.</small> : !partialPaymentAllowed && <small className="pos-error">The remaining amount exceeds this customer’s available credit.</small>}</> : <div className="pos-change-due"><span>Change due</span><strong>{currency(changeDue)}</strong></div>}<div className="pos-cash-shortcuts">{[total, 20, 50].filter((amount, index, list) => amount > 0 && list.indexOf(amount) === index).map((amount) => <button key={amount} onClick={() => setCashTendered(amount.toFixed(2))}>{amount === total ? 'Exact' : currency(amount)}</button>)}</div></div>}
          {paymentMethod === 'account' && <div className="pos-cash-entry pos-account-summary"><div><span>Customer</span><strong>{selectedCustomer?.name ?? 'Select a customer'}</strong></div><div><span>Available credit</span><strong>{currency(availableCredit)}</strong></div>{!accountPaymentAllowed && <small className="pos-error">Select an account with enough approved credit.</small>}</div>}
        </div>
        {invalidUnitPrice && <p className="pos-error">Enter a unit price using no more than two decimal places for each item.</p>}
        {error && <p className="pos-error">{error}</p>}
        <button className="pos-checkout-button" disabled={!cart.length || invalidUnitPrice || saving || (paymentMethod === 'cash' && (cashReceived <= 0 || !partialPaymentAllowed)) || (paymentMethod === 'account' && !accountPaymentAllowed)} onClick={() => void completeSale()}>{saving ? 'Processing payment…' : <><CreditCard size={16}/>{paymentMethod === 'account' ? 'Charge account' : 'Complete sale'}</>}</button>
        <button className="pos-hold-button" disabled={!cart.length} onClick={holdCart}>Hold cart {heldCarts.length ? `(${heldCarts.length})` : ''}</button>
        {heldCarts.length > 0 && <div className="pos-held-carts"><span>HELD CARTS</span>{heldCarts.slice(0, 2).map((held) => <button key={held.id} onClick={() => resumeCart(held)}>{held.customer} · {held.lines.length} products</button>)}</div>}
      </aside>
    </div>}
    <section className="pos-register-footer"><span>Receipt printing available after payment</span><button onClick={onOpenInventory}><Truck size={13}/>View inventory</button><button onClick={() => scannerRef.current?.focus()}><Search size={13}/>Focus scanner</button></section>
    {notice && <div className="catalog-toast"><Check size={15}/>{notice}<button onClick={() => setNotice('')} aria-label="Dismiss"><X size={14}/></button></div>}
    {receipt && <div className="catalog-overlay" onMouseDown={(event) => event.target === event.currentTarget && setReceipt(null)}><section className="catalog-modal pos-receipt-modal"><div className="catalog-modal-heading"><div><span className="catalog-eyebrow">SALE RECORDED</span><h2>Sale receipt</h2><p>{receipt.receipt_number} · {new Date(receipt.created_at).toLocaleString()}</p></div><button className="catalog-icon-button" onClick={() => setReceipt(null)} aria-label="Close"><X size={18}/></button></div><div className="pos-receipt-items">{receipt.items.map((item) => <div key={item.id}><span>{item.quantity} × {item.product_name}</span><strong>{currency(item.line_total)}</strong></div>)}</div><div className="pos-receipt-totals"><div><span>Subtotal</span><strong>{currency(receipt.subtotal)}</strong></div><div><span>Discount</span><strong>−{currency(receipt.discount_amount)}</strong></div><div><span>Tax</span><strong>{currency(receipt.tax_amount)}</strong></div><div className="pos-receipt-final"><span>Total</span><strong>{currency(receipt.total)}</strong></div>{receipt.payment_method === 'cash' && receipt.cash_tendered && <div><span>Amount received</span><strong>{currency(receipt.cash_tendered)}</strong></div>}{Number(receipt.remaining_balance) > 0 && <div><span>Remaining amount due</span><strong>{currency(receipt.remaining_balance)}</strong></div>}{Number(receipt.change_due) > 0 && <div><span>Change due</span><strong>{currency(receipt.change_due)}</strong></div>}{receipt.payment_method === 'account' && <div><span>Payment status</span><strong>{receipt.payment_status === 'paid' ? 'Paid' : 'On account'}</strong></div>}</div><div className="catalog-modal-actions"><button className="catalog-button catalog-button-light" onClick={() => setReceipt(null)}>Done</button><button className="catalog-button catalog-button-primary" onClick={() => window.print()}><Printer size={14}/>Print receipt</button></div></section></div>}
  </>;
}
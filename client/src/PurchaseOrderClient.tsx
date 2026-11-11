import { Fragment, useEffect, useMemo, useState } from 'react';
import { AlertCircle, Check, ClipboardList, Package, Plus, RefreshCw, Search, Trash2, Truck } from 'lucide-react';
import {
  api,
  formatCurrency,
  type BottleCustomerPO,
  type BottleProduct,
  type ClientMaterial,
  type ClientMaterialPO,
  type Customer,
  type Product,
} from './api';
import { useDataRevision } from './dataSync';
import { useConfirmation } from './ConfirmDialog';

type DashboardTab = 'bottle-orders' | 'material-orders' | 'bottle-catalog' | 'material-catalog';
type OrderFilter = 'all' | 'open' | 'partial' | 'completed';
type BottleLineDraft = { product: string; quantity: string; unit_price: string };
type BottleProductDraft = { inventory_product: string; category: string; unit: string; unit_price: string };
type ClientMaterialDraft = { name: string; unit: string; unit_price: string };
type MaterialOrderDraft = { reference: string; customer: string; material: string; quantity: string; unit_price: string; expected_delivery: string; notes: string };

const dateLabel = (value: string | null) => value
  ? new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(`${value.slice(0, 10)}T00:00:00`))
  : 'Not scheduled';

export default function PurchaseOrderClient() {
  const dataRevision = useDataRevision();
  const { confirm, dialog } = useConfirmation();
  const [tab, setTab] = useState<DashboardTab>('bottle-orders');
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [inventoryProducts, setInventoryProducts] = useState<Product[]>([]);
  const [bottleProducts, setBottleProducts] = useState<BottleProduct[]>([]);
  const [bottleOrders, setBottleOrders] = useState<BottleCustomerPO[]>([]);
  const [materials, setMaterials] = useState<ClientMaterial[]>([]);
  const [materialOrders, setMaterialOrders] = useState<ClientMaterialPO[]>([]);
  const [reference, setReference] = useState('');
  const [customerId, setCustomerId] = useState('');
  const [expectedDelivery, setExpectedDelivery] = useState('');
  const [notes, setNotes] = useState('');
  const [bottleLines, setBottleLines] = useState<BottleLineDraft[]>([{ product: '', quantity: '1', unit_price: '' }]);
  const [bottleDraft, setBottleDraft] = useState<BottleProductDraft>({ inventory_product: '', category: 'UGANDA WARAGI', unit: 'bottles', unit_price: '0.00' });
  const [clientMaterialDraft, setClientMaterialDraft] = useState<ClientMaterialDraft>({ name: '', unit: 'kg', unit_price: '0.00' });
  const [materialDraft, setMaterialDraft] = useState<MaterialOrderDraft>({ reference: '', customer: '', material: '', quantity: '', unit_price: '', expected_delivery: '', notes: '' });
  const [deliveryQuantities, setDeliveryQuantities] = useState<Record<number, string>>({});
  const [materialReceiptQuantity, setMaterialReceiptQuantity] = useState('');
  const [selectedBottleOrderId, setSelectedBottleOrderId] = useState<number | null>(null);
  const [historyBottleOrderId, setHistoryBottleOrderId] = useState<number | null>(null);
  const [selectedMaterialOrderId, setSelectedMaterialOrderId] = useState<number | null>(null);
  const [historyMaterialOrderId, setHistoryMaterialOrderId] = useState<number | null>(null);
  const [filter, setFilter] = useState<OrderFilter>('all');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  async function loadData() {
    setLoading(true);
    setError('');
    try {
      const [customerRows, inventoryProductRows, bottleProductRows, bottleOrderRows, materialRows, materialOrderRows] = await Promise.all([
        api.customers(),
        api.products(),
        api.bottleProducts(),
        api.bottleOrders(),
        api.clientMaterials(),
        api.clientMaterialOrders(),
      ]);
      setCustomers(customerRows.filter((customer) => customer.is_active));
      setInventoryProducts(inventoryProductRows.filter((product) => product.is_active));
      setBottleProducts(bottleProductRows);
      setBottleOrders(bottleOrderRows);
      setMaterials(materialRows);
      setMaterialOrders(materialOrderRows);
      setCustomerId((current) => current || String(customerRows.find((customer) => customer.is_active)?.id ?? ''));
      setMaterialDraft((current) => ({
        ...current,
        customer: current.customer || String(customerRows.find((customer) => customer.is_active)?.id ?? ''),
        material: current.material || String(materialRows[0]?.id ?? ''),
        unit_price: current.unit_price || materialRows[0]?.unit_price || '',
      }));
      setBottleLines((current) => current.map((line) => {
        if (line.product) return line;
        const firstActive = bottleProductRows.find((product) => product.is_active);
        return firstActive ? { ...line, product: String(firstActive.id), unit_price: firstActive.unit_price } : line;
      }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load PO Client data from the server.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadData(); }, [dataRevision]);

  const activeBottleProducts = bottleProducts.filter((product) => product.is_active);
  const unlinkedInventoryProducts = inventoryProducts.filter((product) => !bottleProducts.some((bottleProduct) => bottleProduct.id === product.id));
  const selectedInventoryProduct = inventoryProducts.find((product) => product.id === Number(bottleDraft.inventory_product));
  const openBottleOrders = bottleOrders.filter((order) => order.status !== 'completed');
  const openMaterialOrders = materialOrders.filter((order) => order.status !== 'completed');
  const selectedBottleOrder = openBottleOrders.find((order) => order.id === selectedBottleOrderId) ?? openBottleOrders[0] ?? null;
  const selectedMaterialOrder = openMaterialOrders.find((order) => order.id === selectedMaterialOrderId) ?? openMaterialOrders[0] ?? null;
  const filteredBottleOrders = useMemo(() => {
    const term = query.trim().toLowerCase();
    return bottleOrders.filter((order) => {
      const statusMatch = filter === 'all' || order.status === filter;
      const searchMatch = !term || `${order.reference} ${order.customer_name} ${order.items.map((item) => `${item.product_name} ${item.product_sku} ${item.category}`).join(' ')}`.toLowerCase().includes(term);
      return statusMatch && searchMatch;
    });
  }, [bottleOrders, filter, query]);
  const filteredMaterialOrders = useMemo(() => {
    const term = query.trim().toLowerCase();
    return materialOrders.filter((order) => {
      const statusMatch = filter === 'all' || order.status === filter;
      const searchMatch = !term || `${order.reference} ${order.customer_name} ${order.material_name}`.toLowerCase().includes(term);
      return statusMatch && searchMatch;
    });
  }, [filter, materialOrders, query]);
  const bottleOpenValue = bottleOrders.filter((order) => order.status !== 'completed')
    .reduce((sum, order) => sum + order.items.reduce((subtotal, item) => subtotal + item.remaining_quantity * Number(item.unit_price), 0), 0);
  const bottleLineTotalCents = bottleLines.reduce((sum, line) => sum + Math.round(Number(line.unit_price || 0) * 100) * Number(line.quantity || 0), 0);
  const activeMaterial = materials.find((material) => material.id === Number(materialDraft.material));

  function updateBottleLine(index: number, field: keyof BottleLineDraft, value: string) {
    setBottleLines((current) => current.map((line, lineIndex) => {
      if (lineIndex !== index) return line;
      if (field === 'product') {
        const product = bottleProducts.find((row) => row.id === Number(value));
        return { ...line, product: value, unit_price: product?.unit_price ?? '' };
      }
      return { ...line, [field]: value };
    }));
  }

  async function createBottleOrder(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!reference.trim() || !customerId || !bottleLines.length || bottleLines.some((line) => !line.product)) {
      setError('Enter the client PO reference, choose a customer, and select a bottle product for every line.');
      return;
    }
    if (bottleLineTotalCents <= 0 || !Number.isSafeInteger(bottleLineTotalCents)) {
      setError('Enter a valid quantity and unit price for each bottle category.');
      return;
    }
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const created = await api.createBottleOrder({
        reference: reference.trim(),
        customer: Number(customerId),
        expected_delivery: expectedDelivery || null,
        notes: notes.trim(),
        items: bottleLines.map((line) => ({ product: Number(line.product), quantity: Number(line.quantity), unit_price: line.unit_price })),
      });
      await loadData();
      setSelectedBottleOrderId(created.id);
      setReference('');
      setExpectedDelivery('');
      setNotes('');
      setBottleLines([{ product: activeBottleProducts[0] ? String(activeBottleProducts[0].id) : '', quantity: '1', unit_price: activeBottleProducts[0]?.unit_price ?? '' }]);
      setNotice(`${created.reference} saved. Deliveries can be recorded in partial quantities.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not create the customer bottle PO.');
    } finally {
      setSaving(false);
    }
  }

  async function createBottleCatalogItem(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!bottleDraft.inventory_product) {
      setError('Select a product from the Product dashboard first.');
      return;
    }
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const created = await api.createBottleProduct({
        inventory_product: Number(bottleDraft.inventory_product),
        category: bottleDraft.category,
        unit: bottleDraft.unit.trim(),
        unit_price: bottleDraft.unit_price,
      });
      await loadData();
      setBottleDraft({ inventory_product: '', category: 'UGANDA WARAGI', unit: 'bottles', unit_price: '0.00' });
      setNotice(`${created.name} (Product ID ${created.id}) linked to the delivery catalog.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not add this bottle catalog item.');
    } finally {
      setSaving(false);
    }
  }

  async function createClientMaterial(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const created = await api.createClientMaterial({
        name: clientMaterialDraft.name.trim(),
        unit: clientMaterialDraft.unit.trim(),
        unit_price: clientMaterialDraft.unit_price,
      });
      await loadData();
      setClientMaterialDraft({ name: '', unit: 'kg', unit_price: '0.00' });
      setNotice(`${created.name} added to the client-supplied product catalog.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not add this client-supplied product.');
    } finally {
      setSaving(false);
    }
  }

  async function createMaterialOrder(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!materialDraft.reference.trim() || !materialDraft.customer || !materialDraft.material) {
      setError('Enter the client PO reference, customer, and supplied material.');
      return;
    }
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const created = await api.createClientMaterialOrder({
        reference: materialDraft.reference.trim(),
        customer: Number(materialDraft.customer),
        material: Number(materialDraft.material),
        quantity: materialDraft.quantity,
        unit_price: materialDraft.unit_price,
        expected_delivery: materialDraft.expected_delivery || null,
        notes: materialDraft.notes.trim(),
      });
      await loadData();
      setSelectedMaterialOrderId(created.id);
      setMaterialDraft((current) => ({ ...current, reference: '', quantity: '', expected_delivery: '', notes: '' }));
      setNotice(`${created.material_name} PO ${created.reference} saved. Receipts can be recorded in partial quantities.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not create the client-material PO.');
    } finally {
      setSaving(false);
    }
  }

  async function recordBottleDelivery(order: BottleCustomerPO) {
    const items = order.items
      .map((line) => ({ purchase_order_line: line.id, quantity: Number(deliveryQuantities[line.id] || 0) }))
      .filter((line) => line.quantity > 0);
    if (!items.length) {
      setError('Enter a delivery quantity for at least one bottle line.');
      return;
    }
    setBusyId(order.id);
    setError('');
    setNotice('');
    try {
      const updated = await api.deliverBottleOrder(order.id, { items });
      await loadData();
      setSelectedBottleOrderId(updated.id);
      setDeliveryQuantities({});
      setNotice(`${order.reference} delivery saved. PO status: ${updated.status}.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not record this bottle delivery.');
    } finally {
      setBusyId(null);
    }
  }

  async function receiveMaterialOrder(order: ClientMaterialPO) {
    if (!materialReceiptQuantity || Number(materialReceiptQuantity) <= 0) {
      setError(`Enter the ${order.material_unit} quantity received.`);
      return;
    }
    setBusyId(order.id);
    setError('');
    setNotice('');
    try {
      const updated = await api.receiveClientMaterialOrder(order.id, { quantity: materialReceiptQuantity });
      await loadData();
      setSelectedMaterialOrderId(updated.id);
      setMaterialReceiptQuantity('');
      setNotice(`${order.material_name} receipt saved. ${updated.remaining_quantity} ${updated.material_unit} remain on the PO.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not record this material receipt.');
    } finally {
      setBusyId(null);
    }
  }

  async function deleteBottleOrder(order: BottleCustomerPO) {
    const deliveredQuantity = order.items.reduce((total, item) => total + item.delivered_quantity, 0);
    const confirmed = await confirm({
      title: 'Delete client delivery PO?',
      message: `Delete ${order.reference}? This will return ${deliveredQuantity.toLocaleString()} delivered items to inventory and remove its delivery history.`,
      confirmLabel: 'Delete PO and return stock',
      variant: 'danger',
    });
    if (!confirmed) return;

    setBusyId(order.id);
    setError('');
    setNotice('');
    try {
      await api.deleteBottleOrder(order.id);
      await loadData();
      if (selectedBottleOrderId === order.id) setSelectedBottleOrderId(null);
      if (historyBottleOrderId === order.id) setHistoryBottleOrderId(null);
      setNotice(`${order.reference} deleted. ${deliveredQuantity.toLocaleString()} delivered items returned to inventory.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not delete this bottle PO.');
    } finally {
      setBusyId(null);
    }
  }

  async function deleteMaterialOrder(order: ClientMaterialPO) {
    const confirmed = await confirm({
      title: 'Delete client-supplied PO?',
      message: `Delete ${order.reference}? This will remove ${formatQuantity(Number(order.received_quantity))} ${order.material_unit} received against this PO from ${order.material_name} stock. The deletion will be blocked if any of that stock has already been used.`,
      confirmLabel: 'Delete PO and reverse stock',
      variant: 'danger',
    });
    if (!confirmed) return;

    setBusyId(order.id);
    setError('');
    setNotice('');
    try {
      await api.deleteClientMaterialOrder(order.id);
      await loadData();
      if (selectedMaterialOrderId === order.id) setSelectedMaterialOrderId(null);
      if (historyMaterialOrderId === order.id) setHistoryMaterialOrderId(null);
      setNotice(`${order.reference} deleted. Received stock was removed from ${order.material_name}.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not delete this client-supplied PO.');
    } finally {
      setBusyId(null);
    }
  }

  const tabs: Array<{ id: DashboardTab; label: string }> = [
    { id: 'bottle-orders', label: 'Client Delivery POs' },
    { id: 'material-orders', label: 'Client-Supplied POs' },
    { id: 'bottle-catalog', label: 'Delivery Catalog' },
    { id: 'material-catalog', label: 'Client Supply Catalog' },
  ];

  return <div className="po-client-page">
    <header className="po-client-heading">
      <div><div className="po-client-breadcrumb">Procurement <span>›</span> <b>PO Client</b></div><h1>Purchasing Order (PO) Client</h1><p>Track client orders, partial deliveries, and client-supplied products.</p></div>
      <span className="po-client-sync"><i/> Connected to PO services</span>
    </header>

    {error && <div className="po-client-error" role="alert"><AlertCircle size={15}/><span>{error}</span><button type="button" onClick={() => void loadData()}><RefreshCw size={13}/> Retry</button></div>}
    {notice && <div className="po-client-notice" role="status"><Check size={15}/>{notice}<button type="button" onClick={() => setNotice('')} aria-label="Dismiss notice">×</button></div>}

    {loading ? <section className="po-client-loading"><RefreshCw size={17}/> Loading PO Client data…</section> : <>
      <section className="po-client-metrics" aria-label="PO Client summary">
        <article><div><span>OPEN DELIVERY PO VALUE</span><i className="po-icon blue"><ClipboardList size={16}/></i></div><strong>{formatCurrency(bottleOpenValue)}</strong><small>{openBottleOrders.length} POs still being fulfilled</small></article>
        <article><div><span>ITEM DELIVERY QUEUE</span><i className="po-icon indigo"><Truck size={16}/></i></div><strong>{openBottleOrders.reduce((sum, order) => sum + order.items.reduce((subtotal, line) => subtotal + line.remaining_quantity, 0), 0).toLocaleString()} <em>items</em></strong><small>Remaining across open delivery POs</small></article>
        <article><div><span>CLIENT-SUPPLIED STOCK</span><i className="po-icon green"><Check size={16}/></i></div><strong>{materials.length}</strong><small>Products available for receipt tracking</small></article>
        <article><div><span>DELIVERY CATALOG</span><i className="po-icon amber"><Package size={16}/></i></div><strong>{activeBottleProducts.length}</strong><small>Active products available to deliver</small></article>
      </section>

      <nav className="po-client-tabs" aria-label="PO Client sections">{tabs.map((item) => <button key={item.id} type="button" className={tab === item.id ? 'active' : ''} onClick={() => { setTab(item.id); setError(''); setNotice(''); }}>{item.label}</button>)}</nav>

      {tab === 'bottle-orders' && <section className="po-client-workbench">
        <form className="po-generator" onSubmit={(event) => void createBottleOrder(event)}>
          <header><div><span className="po-eyebrow">CUSTOMER PURCHASE ORDER</span><h2>Create Client Delivery PO</h2><p>Enter the client PO and the products and quantities you will deliver.</p></div><i><ClipboardList size={18}/></i></header>
          <div className="po-form-row"><label className="po-field">Client PO reference<input required maxLength={40} value={reference} onChange={(event) => setReference(event.target.value)} placeholder="Client PO number"/></label><label className="po-field">Customer<select required value={customerId} onChange={(event) => setCustomerId(event.target.value)}><option value="">Select customer</option>{customers.map((customer) => <option key={customer.id} value={customer.id}>{customer.name}</option>)}</select></label></div>
          <label className="po-field">Expected delivery date<input type="date" value={expectedDelivery} onChange={(event) => setExpectedDelivery(event.target.value)}/></label>
          <div className="po-lines-heading"><strong>PO product lines</strong><button type="button" onClick={() => setBottleLines((current) => [...current, { product: '', quantity: '1', unit_price: '' }])}><Plus size={13}/> Add item</button></div>
          <div className="po-lines">{bottleLines.map((line, index) => <div className="po-line" key={index}>
            <label className="po-field">Product / category<select required value={line.product} onChange={(event) => updateBottleLine(index, 'product', event.target.value)}><option value="">Select product</option>{activeBottleProducts.map((product) => <option key={product.id} value={product.id}>ID {product.id} · {product.category} · {product.name}</option>)}</select></label>
            <label className="po-field">Qty<input required type="number" min="1" step="1" value={line.quantity} onChange={(event) => updateBottleLine(index, 'quantity', event.target.value)}/></label>
            <label className="po-field">Price / unit<input required type="number" min="0" step="0.01" value={line.unit_price} onChange={(event) => updateBottleLine(index, 'unit_price', event.target.value)}/></label>
            <button className="po-remove-line" type="button" disabled={bottleLines.length === 1} aria-label="Remove product line" onClick={() => setBottleLines((current) => current.filter((_, lineIndex) => lineIndex !== index))}>×</button>
          </div>)}</div>
          <label className="po-field">Order notes<input maxLength={240} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Client delivery instructions"/></label>
          <div className="po-order-total"><span>Calculated client PO amount</span><strong>{formatCurrency(bottleLineTotalCents / 100)}</strong></div>
          <button className="po-primary-button" type="submit" disabled={saving || !customers.length || !activeBottleProducts.length}><Plus size={15}/>{saving ? 'Saving PO…' : 'Save client PO'}</button>
          {!customers.length && <small className="po-form-hint">Add a customer before creating client POs.</small>}
          {!activeBottleProducts.length && <small className="po-form-hint">Add products in Delivery Catalog before creating a PO.</small>}
        </form>

        <section className="po-dock"><header><div className="po-dock-topline"><span className="po-eyebrow">PARTIAL DELIVERY WORKSPACE</span><span className="po-queue-badge"><i/> {openBottleOrders.length} OPEN</span></div>
          {selectedBottleOrder ? <><h2>{selectedBottleOrder.reference}</h2><p>{selectedBottleOrder.customer_name}</p><div className="po-delivery-meta"><span>Due {dateLabel(selectedBottleOrder.expected_delivery)}</span><b>{selectedBottleOrder.status}</b></div></> : <><h2>Delivery terminal</h2><p>No outstanding bottle POs.</p></>}
        </header><div className="po-dock-body">
          {selectedBottleOrder ? <>
            {openBottleOrders.length > 1 && <label className="po-field">Select open PO<select value={selectedBottleOrder.id} onChange={(event) => { setSelectedBottleOrderId(Number(event.target.value)); setDeliveryQuantities({}); }}>{openBottleOrders.map((order) => <option key={order.id} value={order.id}>{order.reference} · {order.customer_name}</option>)}</select></label>}
            <div className="po-dock-items">{selectedBottleOrder.items.filter((line) => line.remaining_quantity > 0).map((line) => {
              const product = bottleProducts.find((row) => row.id === line.product);
              return <div className="po-dock-item po-delivery-line" key={line.id}><i><Package size={14}/></i><span><b>{line.category} · {line.product_name}</b><small>ID {line.product} · {line.product_sku} · {line.delivered_quantity} / {line.quantity} {line.unit} delivered · Product stock {product?.quantity ?? 0} {line.unit}</small></span><label className="po-field">Deliver<input type="number" min="0" max={Math.min(line.remaining_quantity, product?.quantity ?? 0)} step="1" value={deliveryQuantities[line.id] ?? ''} onChange={(event) => setDeliveryQuantities((current) => ({ ...current, [line.id]: event.target.value }))} placeholder="0"/></label></div>;
            })}</div>
            <p className="po-receive-hint">Each delivery reduces stock for this same product ID in the Product dashboard. The PO completes when every ordered line is fully delivered.</p>
            <button className="po-receive-button" disabled={busyId === selectedBottleOrder.id} onClick={() => void recordBottleDelivery(selectedBottleOrder)}><Truck size={15}/>{busyId === selectedBottleOrder.id ? 'Saving delivery…' : 'Record partial delivery'}</button>
            {selectedBottleOrder.deliveries.length > 0 && <div className="po-receipt-history"><strong>Delivery history</strong>{selectedBottleOrder.deliveries.map((delivery) => <div key={delivery.id}><span><b>{delivery.reference}</b><small>{dateLabel(delivery.delivered_at)}</small></span><span>{delivery.items.map((item) => `${item.quantity} ${item.unit} × ${item.product_name}`).join(', ')}</span></div>)}</div>}
          </> : <div className="po-dock-empty"><Truck size={24}/><span>Create a customer bottle PO to start delivery tracking.</span></div>}
        </div></section>
      </section>}

      {tab === 'material-orders' && <section className="po-client-workbench">
        <form className="po-generator" onSubmit={(event) => void createMaterialOrder(event)}>
          <header><div><span className="po-eyebrow">CLIENT-SUPPLIED PRODUCTS</span><h2>Register Client-Supplied PO</h2><p>Create a client PO for Spent Yeast, Ash, or any item in the Client Supply Catalog.</p></div><i><Package size={18}/></i></header>
          <label className="po-field">Client PO reference<input required maxLength={40} value={materialDraft.reference} onChange={(event) => setMaterialDraft((current) => ({ ...current, reference: event.target.value }))} placeholder="Client material PO number"/></label>
          <div className="po-form-row"><label className="po-field">Customer<select required value={materialDraft.customer} onChange={(event) => setMaterialDraft((current) => ({ ...current, customer: event.target.value }))}><option value="">Select customer</option>{customers.map((customer) => <option key={customer.id} value={customer.id}>{customer.name}</option>)}</select></label><label className="po-field">Product supplied<select required value={materialDraft.material} onChange={(event) => { const material = materials.find((item) => item.id === Number(event.target.value)); setMaterialDraft((current) => ({ ...current, material: event.target.value, unit_price: material?.unit_price ?? '' })); }}><option value="">Select product</option>{materials.map((material) => <option key={material.id} value={material.id}>{material.name} · {formatCurrency(material.unit_price)}/{material.unit}</option>)}</select></label></div>
          <div className="po-form-row"><label className="po-field">Ordered quantity ({activeMaterial?.unit ?? 'kg'})<input required type="number" min="0.01" step="0.01" value={materialDraft.quantity} onChange={(event) => setMaterialDraft((current) => ({ ...current, quantity: event.target.value }))}/></label><label className="po-field">Price per {activeMaterial?.unit ?? 'kg'} (UGX)<input required type="number" min="0" step="0.01" value={materialDraft.unit_price} onChange={(event) => setMaterialDraft((current) => ({ ...current, unit_price: event.target.value }))}/></label></div>
          <label className="po-field">Expected delivery<input type="date" value={materialDraft.expected_delivery} onChange={(event) => setMaterialDraft((current) => ({ ...current, expected_delivery: event.target.value }))}/></label>
          <label className="po-field">Notes<input maxLength={240} value={materialDraft.notes} onChange={(event) => setMaterialDraft((current) => ({ ...current, notes: event.target.value }))} placeholder="Receipt or quality notes"/></label>
          <div className="po-order-total"><span>PO amount</span><strong>{formatCurrency(Number(materialDraft.quantity || 0) * Number(materialDraft.unit_price || 0))}</strong></div>
          <button className="po-primary-button" type="submit" disabled={saving || !customers.length || !materials.length}><Plus size={15}/>{saving ? 'Saving PO…' : 'Save client-supplied PO'}</button>
        </form>
        <section className="po-dock"><header><div className="po-dock-topline"><span className="po-eyebrow">MATERIAL RECEIVING</span><span className="po-queue-badge"><i/> {openMaterialOrders.length} OPEN</span></div>
          {selectedMaterialOrder ? <><h2>{selectedMaterialOrder.reference}</h2><p>{selectedMaterialOrder.customer_name} · {selectedMaterialOrder.material_name}</p><div className="po-delivery-meta"><span>{selectedMaterialOrder.received_quantity} / {selectedMaterialOrder.quantity} {selectedMaterialOrder.material_unit} received</span><b>{selectedMaterialOrder.remaining_quantity} remaining</b></div></> : <><h2>Material receiving</h2><p>No client-material POs awaiting receipt.</p></>}
        </header><div className="po-dock-body">{selectedMaterialOrder ? <>
          {openMaterialOrders.length > 1 && <label className="po-field">Select material PO<select value={selectedMaterialOrder.id} onChange={(event) => { setSelectedMaterialOrderId(Number(event.target.value)); setMaterialReceiptQuantity(''); }}>{openMaterialOrders.map((order) => <option key={order.id} value={order.id}>{order.reference} · {order.material_name}</option>)}</select></label>}
          <div className="po-material-stock"><span>Current {selectedMaterialOrder.material_name} stock</span><strong>{materials.find((item) => item.id === selectedMaterialOrder.material)?.quantity ?? '0'} {selectedMaterialOrder.material_unit}</strong></div>
          <label className="po-field">Quantity received now ({selectedMaterialOrder.material_unit})<input type="number" min="0.01" max={selectedMaterialOrder.remaining_quantity} step="0.01" value={materialReceiptQuantity} onChange={(event) => setMaterialReceiptQuantity(event.target.value)} placeholder="Enter received quantity"/></label>
          <p className="po-receive-hint">Each receipt adds the supplied product to its stock and updates the PO completion progress.</p>
          <button className="po-receive-button" disabled={busyId === selectedMaterialOrder.id} onClick={() => void receiveMaterialOrder(selectedMaterialOrder)}><Check size={15}/>{busyId === selectedMaterialOrder.id ? 'Recording receipt…' : 'Record material receipt'}</button>
          {selectedMaterialOrder.receipts.length > 0 && <div className="po-receipt-history"><strong>Receipt history</strong>{selectedMaterialOrder.receipts.map((receipt) => <div key={receipt.id}><span><b>{receipt.reference}</b><small>{dateLabel(receipt.received_at)}</small></span><span>{receipt.quantity} {selectedMaterialOrder.material_unit}</span></div>)}</div>}
        </> : <div className="po-dock-empty"><Package size={24}/><span>Create a client-supplied PO to record product receipts.</span></div>}</div></section>
      </section>}

      {tab === 'bottle-catalog' && <section className="po-catalog-layout">
        <form className="po-generator" onSubmit={(event) => void createBottleCatalogItem(event)}>
          <header><div><span className="po-eyebrow">CLIENT DELIVERY PRODUCT CATALOG</span><h2>Link a Product dashboard item</h2><p>Select an existing product. Client POs use that product’s ID and on-hand stock directly.</p></div><i><Package size={18}/></i></header>
          <label className="po-field">Product from Product dashboard<select required value={bottleDraft.inventory_product} onChange={(event) => { const product = inventoryProducts.find((row) => row.id === Number(event.target.value)); setBottleDraft((current) => ({ ...current, inventory_product: event.target.value, unit_price: product?.unit_price ?? current.unit_price })); }}><option value="">Select a product</option>{unlinkedInventoryProducts.map((product) => <option key={product.id} value={product.id}>ID {product.id} · {product.name} · {product.sku} · Stock {product.quantity}</option>)}</select></label>
          {selectedInventoryProduct && <p className="po-form-hint">Product ID {selectedInventoryProduct.id} · Current stock {selectedInventoryProduct.quantity}</p>}
          <label className="po-field">Category<input required maxLength={80} list="po-delivery-categories" value={bottleDraft.category} onChange={(event) => setBottleDraft((current) => ({ ...current, category: event.target.value }))} placeholder="Product category"/><datalist id="po-delivery-categories"><option value="UGANDA WARAGI"/><option value="GUARANTEE"/></datalist></label>
          <label className="po-field">Stock unit<input required maxLength={24} value={bottleDraft.unit} onChange={(event) => setBottleDraft((current) => ({ ...current, unit: event.target.value }))} placeholder="bottles, boxes, pieces"/></label>
          <label className="po-field">Default price / unit (UGX)<input required type="number" min="0" step="0.01" value={bottleDraft.unit_price} onChange={(event) => setBottleDraft((current) => ({ ...current, unit_price: event.target.value }))}/></label>
          <button className="po-primary-button" type="submit" disabled={saving || !unlinkedInventoryProducts.length || !bottleDraft.inventory_product}>{saving ? 'Linking product…' : 'Link to delivery catalog'}</button>
          {!unlinkedInventoryProducts.length && <small className="po-form-hint">{inventoryProducts.length ? 'All active products are already linked to the delivery catalog.' : 'Add an active product in the Product dashboard before linking it here.'}</small>}
        </form>
        <section className="po-register"><header><div><span className="po-eyebrow">DELIVERY PRODUCTS</span><h2>Available delivery inventory</h2><p>Product IDs and stock are shared with the Product dashboard.</p></div><span className="po-order-count">{activeBottleProducts.length} products</span></header>
          <div className="po-register-scroll"><table><thead><tr><th>PRODUCT ID</th><th>CATEGORY</th><th>SKU / PRODUCT</th><th>AVAILABLE</th><th>DEFAULT PRICE</th><th>STATUS</th></tr></thead><tbody>{bottleProducts.map((product) => <tr key={product.id}><td>{product.id}</td><td><span className="po-status open">{product.category}</span></td><td><b>{product.sku}</b><small>{product.name}</small></td><td>{product.quantity.toLocaleString()} {product.unit}</td><td>{formatCurrency(product.unit_price)} / {product.unit}</td><td>{product.is_active ? 'Active' : 'Inactive'}</td></tr>)}{!bottleProducts.length && <tr><td className="po-table-empty" colSpan={6}>Add a product you deliver to clients to start.</td></tr>}</tbody></table></div>
        </section>
      </section>}

      {tab === 'material-catalog' && <section className="po-catalog-layout">
        <form className="po-generator" onSubmit={(event) => void createClientMaterial(event)}>
          <header><div><span className="po-eyebrow">CLIENT-SUPPLIED PRODUCT CATALOG</span><h2>Add a product clients supply</h2><p>Products added here can be selected on a client-supplied PO and tracked through partial receipts.</p></div><i><Package size={18}/></i></header>
          <label className="po-field">Product name<input required maxLength={120} value={clientMaterialDraft.name} onChange={(event) => setClientMaterialDraft((current) => ({ ...current, name: event.target.value }))} placeholder="e.g. Spent Yeast, Ash, or another item"/></label>
          <div className="po-form-row"><label className="po-field">Stock unit<input required maxLength={16} value={clientMaterialDraft.unit} onChange={(event) => setClientMaterialDraft((current) => ({ ...current, unit: event.target.value }))} placeholder="kg, litres, pieces"/></label><label className="po-field">Default price per unit (UGX)<input required type="number" min="0" step="0.01" value={clientMaterialDraft.unit_price} onChange={(event) => setClientMaterialDraft((current) => ({ ...current, unit_price: event.target.value }))}/></label></div>
          <button className="po-primary-button" type="submit" disabled={saving}>{saving ? 'Adding product…' : 'Add to client supply catalog'}</button>
        </form>
        <section className="po-register"><header><div><span className="po-eyebrow">CLIENT-SUPPLIED PRODUCTS</span><h2>Receipt inventory</h2><p>Partial client receipts increase these separately tracked stock balances.</p></div><span className="po-order-count">{materials.length} products</span></header>
          <div className="po-register-scroll"><table><thead><tr><th>PRODUCT</th><th>AVAILABLE STOCK</th><th>DEFAULT RATE</th></tr></thead><tbody>{materials.map((material) => <tr key={material.id}><td><b>{material.name}</b></td><td>{formatQuantity(Number(material.quantity))} {material.unit}</td><td>{formatCurrency(material.unit_price)} / {material.unit}</td></tr>)}{!materials.length && <tr><td className="po-table-empty" colSpan={3}>Add a client-supplied product to start tracking receipts.</td></tr>}</tbody></table></div>
        </section>
      </section>}

      {(tab === 'bottle-orders' || tab === 'material-orders') && <section className="po-register">
        <header><div><span className="po-eyebrow">LIVE PROCUREMENT REGISTER</span><h2>{tab === 'bottle-orders' ? 'Client Delivery POs' : 'Client-Supplied Product POs'}</h2><p>{tab === 'bottle-orders' ? 'Track quantities delivered against each client PO.' : 'Each product PO has independent quantity, rate, and receipts.'}</p></div><span className="po-order-count">{tab === 'bottle-orders' ? bottleOrders.length : materialOrders.length} POs</span></header>
        <div className="po-register-controls"><label><Search size={14}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search PO, customer, product"/></label><select aria-label="Filter PO status" value={filter} onChange={(event) => setFilter(event.target.value as OrderFilter)}><option value="all">All statuses</option><option value="open">Open</option><option value="partial">Partially fulfilled</option><option value="completed">Completed</option></select></div>
        <div className="po-register-scroll"><table><thead>{tab === 'bottle-orders' ? <tr><th>CLIENT PO</th><th>CUSTOMER</th><th>PRODUCT CATEGORIES</th><th>ORDERED / DELIVERED</th><th>PO AMOUNT</th><th>EXPECTED</th><th>STATUS</th><th>DELIVERIES</th><th>ACTIONS</th></tr> : <tr><th>CLIENT PO</th><th>CUSTOMER</th><th>SUPPLIED PRODUCT</th><th>ORDERED / RECEIVED</th><th>UNIT RATE</th><th>PO AMOUNT</th><th>STATUS</th><th>RECEIPTS</th><th>ACTIONS</th></tr>}</thead><tbody>
          {tab === 'bottle-orders' ? filteredBottleOrders.map((order) => <Fragment key={order.id}>
            <tr><td><b>{order.reference}</b><small>Created {dateLabel(order.ordered_at)}</small></td><td>{order.customer_name}</td><td>{[...new Set(order.items.map((item) => item.category))].join(', ')}</td><td>{order.items.map((item) => <small key={item.id}>{item.category}: {item.delivered_quantity} / {item.quantity} {item.unit}</small>)}</td><td><b>{formatCurrency(order.total)}</b></td><td>{dateLabel(order.expected_delivery)}</td><td><span className={`po-status ${order.status}`}>{order.status}</span></td><td><button className="po-row-action" type="button" aria-expanded={historyBottleOrderId === order.id} onClick={() => setHistoryBottleOrderId((current) => current === order.id ? null : order.id)}>{historyBottleOrderId === order.id ? 'Hide history' : `View history (${order.deliveries.length})`}</button></td><td><button className="po-delete-button" type="button" disabled={busyId === order.id} onClick={() => void deleteBottleOrder(order)}><Trash2 size={13}/>{busyId === order.id ? 'Deleting…' : 'Delete'}</button></td></tr>
            {historyBottleOrderId === order.id && <tr className="po-order-history-row"><td colSpan={9}><div className="po-order-history">
              <header><div><strong>Delivery history · {order.reference}</strong><small>{order.customer_name} · {order.status} · {order.deliveries.length} deliveries</small></div></header>
              {order.deliveries.length ? <div className="po-order-history-list">{order.deliveries.map((delivery) => <article key={delivery.id}>
                <div><b>{delivery.reference}</b><small>{dateLabel(delivery.delivered_at)}</small></div>
                <ul>{delivery.items.map((item) => <li key={item.id}>{item.quantity.toLocaleString()} × {item.product_name} ({item.product_sku})</li>)}</ul>
                {delivery.notes && <small>{delivery.notes}</small>}
              </article>)}</div> : <p>No deliveries have been recorded for this PO.</p>}
            </div></td></tr>}
          </Fragment>)
            : filteredMaterialOrders.map((order) => <Fragment key={order.id}>
              <tr><td><b>{order.reference}</b><small>Created {dateLabel(order.ordered_at)}</small></td><td>{order.customer_name}</td><td>{order.material_name}</td><td>{order.received_quantity} / {order.quantity} {order.material_unit}</td><td>{formatCurrency(order.unit_price)} / {order.material_unit}</td><td><b>{formatCurrency(order.total)}</b></td><td><span className={`po-status ${order.status}`}>{order.status}</span></td><td><button className="po-row-action" type="button" aria-expanded={historyMaterialOrderId === order.id} onClick={() => setHistoryMaterialOrderId((current) => current === order.id ? null : order.id)}>{historyMaterialOrderId === order.id ? 'Hide history' : `View history (${order.receipts.length})`}</button></td><td><button className="po-delete-button" type="button" disabled={busyId === order.id} onClick={() => void deleteMaterialOrder(order)}><Trash2 size={13}/>{busyId === order.id ? 'Deleting…' : 'Delete'}</button></td></tr>
              {historyMaterialOrderId === order.id && <tr className="po-order-history-row"><td colSpan={9}><div className="po-order-history">
                <header><div><strong>Receipt history · {order.reference}</strong><small>{order.customer_name} · {order.material_name} · {order.status} · {order.receipts.length} receipts</small></div></header>
                {order.receipts.length ? <div className="po-order-history-list">{order.receipts.map((receipt) => <article key={receipt.id}>
                  <div><b>{receipt.reference}</b><small>{dateLabel(receipt.received_at)}</small></div>
                  <ul><li>{formatQuantity(Number(receipt.quantity))} {order.material_unit} received</li></ul>
                  {receipt.notes && <small>{receipt.notes}</small>}
                </article>)}</div> : <p>No receipts have been recorded for this PO.</p>}
              </div></td></tr>}
            </Fragment>)}
          {tab === 'bottle-orders' && !filteredBottleOrders.length && <tr><td className="po-table-empty" colSpan={8}>No bottle client POs match your filters.</td></tr>}
          {tab === 'material-orders' && !filteredMaterialOrders.length && <tr><td className="po-table-empty" colSpan={8}>No material POs match your filters.</td></tr>}
        </tbody></table></div>
      </section>}
    </>}
    {dialog}
  </div>;
}

function formatQuantity(value: number) {
  return new Intl.NumberFormat('en', { maximumFractionDigits: 2 }).format(value);
}

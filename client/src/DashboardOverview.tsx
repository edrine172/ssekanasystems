import { useEffect, useRef, useState } from 'react';
import { ArrowDownRight, ArrowUpRight, Boxes, ChartNoAxesCombined, ChevronDown, CircleAlert, ListFilter, Package, RefreshCw, TrendingUp, Truck } from 'lucide-react';
import { api, formatCurrency as currency, type DashboardSummary, type StockMovement } from './api';
import { useDataRevision } from './dataSync';

const FLOW_RANGES = [
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
type FlowRange = typeof FLOW_RANGES[number]['value'];
const daysForFlowRange = (range: FlowRange) => FLOW_RANGES.find((option) => option.value === range)!.days;
const currentMonth = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
};
const currentDate = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
};

export default function DashboardOverview({ onOpenProducts, onOpenInventory, onOpenPurchases, onOpenPOS, onOpenReports, onOpenExpenses }: { onOpenProducts: () => void; onOpenInventory: () => void; onOpenPurchases: () => void; onOpenPOS: () => void; onOpenReports: () => void; onOpenExpenses: () => void }) {
  const dataRevision = useDataRevision();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [flowRange, setFlowRange] = useState<FlowRange>('1d');
  const [flowMonthMode, setFlowMonthMode] = useState(false);
  const [flowDayMode, setFlowDayMode] = useState(false);
  const [flowMonth, setFlowMonth] = useState(currentMonth);
  const [flowDate, setFlowDate] = useState(currentDate);
  const [flowMovements, setFlowMovements] = useState<StockMovement[]>([]);
  const [flowLoading, setFlowLoading] = useState(false);
  const [flowError, setFlowError] = useState('');
  const flowRequest = useRef(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  async function loadSummary() {
    setLoading(true);
    setError('');
    try {
      setSummary(await api.summary());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The dashboard could not be loaded.');
    } finally {
      setLoading(false);
    }
  }

  async function loadInventoryFlow(range: FlowRange = flowRange, month?: string, date?: string) {
    const requestId = ++flowRequest.current;
    setFlowLoading(true);
    setFlowError('');
    try {
      const movements = await api.movements(date || month ? undefined : daysForFlowRange(range), month, date);
      if (requestId === flowRequest.current) setFlowMovements(movements);
    } catch (cause) {
      if (requestId === flowRequest.current) setFlowError(cause instanceof Error ? cause.message : 'Inventory flow could not be loaded.');
    } finally {
      if (requestId === flowRequest.current) setFlowLoading(false);
    }
  }

  useEffect(() => { void loadSummary(); void loadInventoryFlow(); }, [dataRevision]);

  const maxTrend = summary ? Math.max(...summary.series.flatMap((day) => [day.sales, day.purchases]), 1) : 1;
  const labelIndexes = summary ? new Set([0, Math.floor((summary.series.length - 1) / 2), summary.series.length - 1]) : new Set<number>();

  return <>
    <section className="catalog-heading overview-heading">
      <div><div className="catalog-breadcrumb"><b>Business overview</b></div><h1>Dashboard</h1><p>Sales, stock health, and recent inventory activity at a glance.</p></div>
      <div className="catalog-heading-actions"><button className="catalog-button catalog-button-light" onClick={onOpenPOS}><Package size={15}/>Open register</button><button className="catalog-button catalog-button-light" onClick={onOpenInventory}><Boxes size={15}/>Inventory</button><button className="catalog-button catalog-button-light" onClick={onOpenPurchases}><Truck size={15}/>Purchases</button><button className="catalog-button catalog-button-light" onClick={onOpenExpenses}><ListFilter size={15}/>Expenses</button><button className="catalog-button catalog-button-light" onClick={onOpenReports}><ChartNoAxesCombined size={15}/>Reports</button><button className="catalog-button catalog-button-primary" onClick={onOpenProducts}><Package size={15}/>Open product catalog</button></div>
    </section>
    {loading && <section className="overview-state">Loading dashboard data…</section>}
    {!loading && error && <section className="overview-state overview-error"><strong>Could not load dashboard data</strong><span>{error}</span><button className="catalog-button catalog-button-light" onClick={() => void loadSummary()}><RefreshCw size={14}/>Retry</button></section>}
    {!loading && summary && <div className="overview-content">
      <section className="overview-metrics" aria-label="Business metrics">
        <article><span>INVENTORY VALUE</span><strong>{currency(summary.inventory_value)}</strong><small><Boxes size={13}/> {summary.total_units.toLocaleString()} units on hand</small></article>
        <article><span>PRODUCT SKUS</span><strong>{summary.total_skus.toLocaleString()}</strong><small><Package size={13}/> Active catalog items</small></article>
        <article className="overview-alert-metric"><span>STOCK NEEDS ATTENTION</span><strong>{(summary.low_stock_count + summary.out_of_stock_count).toLocaleString()}</strong><small><CircleAlert size={13}/> {summary.out_of_stock_count} out of stock</small></article>
        <article><span>GROSS PROFIT · 30 DAYS</span><strong>{currency(summary.gross_profit)}</strong><small><TrendingUp size={13}/> {summary.gross_margin}% gross margin</small></article>
      </section>

      <div className="overview-grid">
        <section className="overview-panel overview-trend-panel">
          <div className="overview-panel-heading"><div><span>PERFORMANCE</span><h2>Sales &amp; purchases</h2></div><span className="overview-period">Last 30 days</span></div>
          <div className="overview-legend"><span><i className="sales-dot"/>Sales {currency(summary.period_sales)}</span><span><i className="purchase-dot"/>Purchases {currency(summary.period_purchases)}</span></div>
          <div className="overview-chart" role="img" aria-label="Daily sales and purchases for the last 30 days">
            {summary.series.map((day) => <div className="overview-chart-day" key={day.label} title={`${day.label}: sales ${currency(day.sales)}, purchases ${currency(day.purchases)}`}>
              <div className="overview-bars"><i className="overview-sales-bar" style={{ height: `${Math.max(day.sales / maxTrend * 100, day.sales ? 3 : 0)}%` }}/><i className="overview-purchase-bar" style={{ height: `${Math.max(day.purchases / maxTrend * 100, day.purchases ? 3 : 0)}%` }}/></div>
            </div>)}
          </div>
          <div className="overview-chart-labels">{summary.series.map((day, index) => labelIndexes.has(index) ? <span key={day.label}>{day.label}</span> : <span key={day.label}/>)}</div>
        </section>

        <section className="overview-panel overview-stock-panel">
          <div className="overview-panel-heading"><div><span>REPLENISHMENT</span><h2>Stock to review</h2></div><button className="overview-text-action" onClick={onOpenInventory}>View inventory</button></div>
          {summary.products.length === 0 ? <p className="overview-empty">No products in the catalog yet.</p> : <div className="overview-stock-list">{summary.products.slice(0, 5).map((product) => {
            const out = product.quantity === 0;
            const low = !out && product.quantity <= product.reorder_level;
            return <button className="overview-stock-row" key={product.id} onClick={onOpenInventory}>
              <span className={`overview-stock-icon ${out ? 'is-out' : low ? 'is-low' : ''}`}><Package size={15}/></span>
              <span className="overview-stock-copy"><strong>{product.name}</strong><small>{product.sku} · Min. {product.reorder_level}</small></span>
              <span className={`overview-stock-quantity ${out ? 'is-out' : low ? 'is-low' : ''}`}>{product.quantity}<small>{out ? 'out' : low ? 'low' : 'units'}</small></span>
            </button>;
          })}</div>}
        </section>
      </div>

      <section className="overview-panel overview-activity-panel">
        <div className="overview-panel-heading"><div><span>INVENTORY FLOW</span><h2>Movement history</h2></div><div className="overview-flow-controls"><label className="catalog-select"><select aria-label="Inventory flow history range" value={flowDayMode ? 'day' : flowMonthMode ? 'month' : flowRange} onChange={(event) => { if (event.target.value === 'day') { setFlowDayMode(true); setFlowMonthMode(false); void loadInventoryFlow(flowRange, undefined, flowDate); } else if (event.target.value === 'month') { setFlowMonthMode(true); setFlowDayMode(false); void loadInventoryFlow(flowRange, flowMonth); } else { const range = event.target.value as FlowRange; setFlowMonthMode(false); setFlowDayMode(false); setFlowRange(range); void loadInventoryFlow(range); } }}><optgroup label="Rolling history">{FLOW_RANGES.map((range) => <option key={range.value} value={range.value}>{range.label}</option>)}</optgroup><option value="day">Choose a day</option><option value="month">Choose month &amp; year</option></select><ChevronDown size={13}/></label>{flowDayMode && <input className="overview-flow-month-picker" type="date" aria-label="Select inventory flow day" value={flowDate} onChange={(event) => { setFlowDate(event.target.value); if (event.target.value) void loadInventoryFlow(flowRange, undefined, event.target.value); }}/>}{flowMonthMode && <input className="overview-flow-month-picker" type="month" aria-label="Select inventory flow month and year" value={flowMonth} onChange={(event) => { setFlowMonth(event.target.value); if (event.target.value) void loadInventoryFlow(flowRange, event.target.value); }}/>}</div></div>
        {flowLoading ? <p className="overview-empty">Loading inventory flow…</p> : flowError ? <div className="overview-empty">{flowError} <button className="overview-text-action" onClick={() => void loadInventoryFlow(flowRange, flowMonthMode ? flowMonth : undefined, flowDayMode ? flowDate : undefined)}>Retry</button></div> : flowMovements.length === 0 ? <p className="overview-empty">No inventory movements in the selected period.</p> : <div className="overview-activity-list">{flowMovements.map((movement) => {
          const inbound = movement.movement_type === 'inbound' || movement.movement_type === 'return';
          const movementLabel = movement.movement_type.replace('_', ' ');
          return <div className="overview-activity-row" key={movement.id}>
            <span className={`overview-movement-icon ${inbound ? 'is-inbound' : ''}`}>{inbound ? <ArrowDownRight size={15}/> : <ArrowUpRight size={15}/>}</span>
            <span className="overview-activity-copy"><strong>{movement.product_name}</strong><small>{movementLabel} · {movement.reference || movement.note || movement.product_sku}</small></span>
            <span className={`overview-movement-quantity ${inbound ? 'is-inbound' : ''}`}>{inbound ? '+' : '−'}{movement.quantity}</span>
            <time>{new Intl.DateTimeFormat('en-US', { year: 'numeric', month: 'short', day: 'numeric' }).format(new Date(movement.created_at))}</time>
          </div>;
        })}</div>}
      </section>
    </div>}
  </>;
}
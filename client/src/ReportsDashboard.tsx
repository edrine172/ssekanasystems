import { useEffect, useState } from 'react';
import { Boxes, BriefcaseBusiness, ChartNoAxesCombined, Landmark, Package, Pencil, RefreshCw, ShoppingCart, TrendingUp, Truck, X } from 'lucide-react';
import { api, formatCurrency as currency, getCurrencyDisplay, type BalanceSheetCategory, type BalanceSheetSection, type BalanceSheetSummary, type ReportsSummary } from './api';
import FileActionMenu from './FileActionMenu';

type ReportTab = 'sales' | 'inventory' | 'purchases' | 'financial' | 'balance-sheet';
type DateRange = '1d' | '7d' | '30d' | '90d' | '180d' | '365d' | '730d' | '1825d' | '3650d' | '18250d' | '36500d' | '73000d';
const dateLabel = (value: string) => new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(`${value}T00:00:00`));
const currentMonth = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
};
const currentDate = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
};
const reportTabs: Array<{ value: ReportTab; label: string; icon: typeof ChartNoAxesCombined }> = [
  { value: 'sales', label: 'Sales reports', icon: ChartNoAxesCombined },
  { value: 'inventory', label: 'Inventory reports', icon: Package },
  { value: 'purchases', label: 'Purchases reports', icon: ShoppingCart },
  { value: 'financial', label: 'Financial & P&L', icon: BriefcaseBusiness },
  { value: 'balance-sheet', label: 'Balance sheet', icon: Landmark },
];
const palette = ['#2865e9', '#43bd8b', '#e6a23c', '#e4675e', '#7888b8', '#2f9eaf'];

function balanceSheetExportRows(sheet: BalanceSheetSummary): Array<Array<string | number>> {
  const rows: Array<Array<string | number>> = [
    ['Balance sheet as of', sheet.as_of_date],
    [],
    ['Section', 'Account', 'Current balance'],
  ];
  const sections: Array<{ label: string; section: BalanceSheetSection }> = [
    { label: 'Assets', section: sheet.assets },
    { label: 'Liabilities', section: sheet.liabilities },
    { label: 'Shareholders’ equity', section: sheet.equity },
  ];
  sections.forEach(({ label, section }) => {
    section.groups.forEach((group) => {
      rows.push([label, group.title, '']);
      group.rows.forEach((account) => rows.push([label, account.name, account.current_amount ?? '—']));
      rows.push([label, `${group.title} total`, group.current_complete ? group.current_total : '—']);
    });
    rows.push([label, `Total ${label.toLowerCase()}`, section.current_complete ? section.current_total : '—']);
  });
  rows.push([
    'Summary',
    'Total liabilities and shareholders’ equity',
    sheet.liabilities.current_complete && sheet.equity.current_complete
      ? (Number(sheet.total_liabilities) + Number(sheet.total_equity)).toFixed(2)
      : '—',
  ]);
  rows.push(['Balance check', sheet.is_balanced ? 'Balanced' : sheet.current_complete ? 'Out of balance' : 'Incomplete', '']);
  rows.push(['Difference', sheet.difference, '']);
  return rows;
}

function BalanceSheetReport({ sheet, onRefresh }: { sheet: BalanceSheetSummary; onRefresh: () => Promise<void> }) {
  const [editing, setEditing] = useState<{
    category: BalanceSheetCategory;
    name: string;
    manual_current_amount: string | null;
    source: string;
    editable_current: boolean;
  } | null>(null);
  const [currentAmount, setCurrentAmount] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  function startEdit(account: NonNullable<typeof editing>) {
    setEditing(account);
    setCurrentAmount(account.manual_current_amount ?? '');
    setError('');
  }

  async function saveAccount(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing) return;
    setSaving(true);
    setError('');
    try {
      await api.updateBalanceSheetAccount(editing.category, { amount: currentAmount });
      setEditing(null);
      await onRefresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save this account balance.');
    } finally {
      setSaving(false);
    }
  }

  const sections: Array<{ key: 'assets' | 'liabilities' | 'equity'; title: string; total: string; section: BalanceSheetSection }> = [
    { key: 'assets', title: 'Assets', total: sheet.total_assets, section: sheet.assets },
    { key: 'liabilities', title: 'Liabilities', total: sheet.total_liabilities, section: sheet.liabilities },
    { key: 'equity', title: 'Shareholders’ equity', total: sheet.total_equity, section: sheet.equity },
  ];
  const date = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    .format(new Date(`${sheet.as_of_date}T00:00:00`));

  return <section className="overview-panel expense-balance-panel" aria-label="Balance sheet report">
    <div className="overview-panel-heading">
      <div><span>FINANCIAL POSITION</span><h2>Balance sheet</h2></div>
      <div className="expense-balance-heading-actions"><span>As of {date}</span></div>
    </div>
    <p className="expense-balance-note">Current inventory, receivables, payables, and approved unpaid expenses are linked automatically. Enter the remaining current balances. Verify manually entered amounts against your accounting records.</p>
    <div className={`expense-balance-status ${sheet.is_balanced ? 'balanced' : 'unbalanced'}`}>
      <strong>{!sheet.current_complete ? 'Current year incomplete' : sheet.is_balanced ? 'Current year balanced' : 'Current year out of balance'}</strong>
      <span>{!sheet.current_complete ? 'Enter a current balance for every category to check the totals.' : sheet.is_balanced ? 'Assets equal liabilities plus equity.' : `Difference: ${currency(sheet.difference)}`}</span>
    </div>
    <div className="expense-balance-sections">{sections.map(({ key, title, total, section }) => <section key={key} className="expense-balance-section">
      <div className="expense-balance-section-heading"><h3>{title}</h3><strong>{section.current_complete ? currency(total) : '—'}</strong></div>
      <div className="expense-balance-year-heading"><span></span><strong>{sheet.current_year}</strong><span></span></div>
      {section.groups.map((group) => <div className="expense-balance-group" key={group.title}>
        <div className="expense-balance-group-heading"><strong>{group.title}</strong><span>{group.current_complete ? currency(group.current_total) : '—'}</span></div>
        {group.rows.map((row) => <div className="expense-balance-row" key={row.category}>
          <div><strong>{row.name}</strong><small>{row.source}</small></div>
          <strong>{row.current_amount === null ? '—' : currency(row.current_amount)}</strong>
          {row.editable_current && <button type="button" className="catalog-icon-button" onClick={() => startEdit(row)} aria-label={`Edit ${row.name} balance`}><Pencil size={12}/></button>}
        </div>)}
      </div>)}
    </section>)}</div>
    <div className="expense-balance-totals">
      {[{ label: 'Total assets', section: sheet.assets, current: sheet.total_assets }, { label: 'Total liabilities', section: sheet.liabilities, current: sheet.total_liabilities }, { label: 'Total shareholders’ equity', section: sheet.equity, current: sheet.total_equity }].map((total) => <div key={total.label}><span>{total.label}</span><strong>{total.section.current_complete ? currency(total.current) : '—'}</strong></div>)}
      <div><span>Total liabilities and shareholders’ equity</span><strong>{sheet.liabilities.current_complete && sheet.equity.current_complete ? currency(Number(sheet.total_liabilities) + Number(sheet.total_equity)) : '—'}</strong></div>
    </div>
    {editing && <div className="catalog-overlay" onMouseDown={(event) => event.target === event.currentTarget && setEditing(null)}><form className="catalog-modal expense-balance-form" onSubmit={(event) => void saveAccount(event)}>
      <div className="catalog-modal-heading"><div><span className="catalog-eyebrow">BALANCE SHEET</span><h2>{editing.name}</h2><p>Enter this account’s current balance.</p></div><button className="catalog-icon-button" type="button" onClick={() => setEditing(null)} aria-label="Close"><X size={18}/></button></div>
      <label className="catalog-field">{sheet.current_year} {editing.editable_current && editing.source !== 'Manual balance' ? 'additional balance' : 'balance'}<input required type="number" step="0.01" value={currentAmount} onChange={(event) => setCurrentAmount(event.target.value)} disabled={!editing.editable_current}/></label>
      {!editing.editable_current && <p className="expense-balance-source-note">This value is calculated from live business records.</p>}
      {editing.editable_current && editing.source !== 'Manual balance' && <p className="expense-balance-source-note">Approved unpaid expenses are included automatically. Add other current liabilities here.</p>}
      {error && <p className="catalog-form-error">{error}</p>}
      <div className="catalog-modal-actions"><button type="button" className="catalog-button catalog-button-light" onClick={() => setEditing(null)}>Cancel</button><button className="catalog-button catalog-button-primary" disabled={saving}>{saving ? 'Saving…' : 'Save balance'}</button></div>
    </form></div>}
  </section>;
}

export default function ReportsDashboard({ onOpenInventory, onOpenPurchases, onOpenPOS, onOpenExpenses }: {
  onOpenInventory: () => void;
  onOpenPurchases: () => void;
  onOpenPOS: () => void;
  onOpenExpenses: () => void;
}) {
  const [report, setReport] = useState<ReportsSummary | null>(null);
  const [balanceSheet, setBalanceSheet] = useState<BalanceSheetSummary | null>(null);
  const [balanceSheetLoading, setBalanceSheetLoading] = useState(true);
  const [balanceSheetError, setBalanceSheetError] = useState('');
  const [activeTab, setActiveTab] = useState<ReportTab>('sales');
  const [range, setRange] = useState<DateRange>('30d');
  const [monthMode, setMonthMode] = useState(false);
  const [dayMode, setDayMode] = useState(false);
  const [selectedMonth, setSelectedMonth] = useState(currentMonth);
  const [selectedDate, setSelectedDate] = useState(currentDate);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  async function loadReport(selectedRange: DateRange = range, month?: string, date?: string) {
    setLoading(true);
    setError('');
    try {
      setReport(await api.reportsSummary(selectedRange, month, date));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Reports could not be loaded.');
    } finally {
      setLoading(false);
    }
  }

  async function loadBalanceSheet() {
    setBalanceSheetLoading(true);
    setBalanceSheetError('');
    try {
      setBalanceSheet(await api.balanceSheet());
    } catch (cause) {
      setBalanceSheetError(cause instanceof Error ? cause.message : 'The balance sheet could not be loaded.');
    } finally {
      setBalanceSheetLoading(false);
    }
  }

  useEffect(() => { void loadReport(range, monthMode ? selectedMonth : undefined, dayMode ? selectedDate : undefined); }, [range, monthMode, selectedMonth, dayMode, selectedDate]);
  useEffect(() => { void loadBalanceSheet(); }, []);

  const series = report?.daily_series ?? [];
  const chartSeries = (() => {
    if (!report) return [];
    if (report.series_interval !== 'day') return series;
    const groups = new Map<string, { label: string; revenue: number; cost_of_goods: number; gross_profit: number; purchases: number; expenses: number; net_profit: number }>();
    series.forEach((day, index) => {
      const date = new Date(`${report.start_date}T00:00:00`);
      date.setDate(date.getDate() + index);
      const monthly = !monthMode && range === '365d';
      const weekly = !monthMode && (range === '90d' || range === '180d');
      const key = monthly ? `${date.getFullYear()}-${date.getMonth()}` : weekly ? String(Math.floor(index / 7)) : String(index);
      const label = monthly ? new Intl.DateTimeFormat('en-US', { month: 'short', year: '2-digit' }).format(date) : day.label;
      const existing = groups.get(key);
      if (existing) {
        existing.revenue += day.revenue;
        existing.cost_of_goods += day.cost_of_goods;
        existing.gross_profit += day.gross_profit;
        existing.purchases += day.purchases;
        existing.expenses += day.expenses;
        existing.net_profit += day.net_profit;
      } else {
        groups.set(key, { label, revenue: day.revenue, cost_of_goods: day.cost_of_goods, gross_profit: day.gross_profit, purchases: day.purchases, expenses: day.expenses, net_profit: day.net_profit });
      }
    });
    return [...groups.values()];
  })();
  const labelIndexes = new Set([0, Math.floor((chartSeries.length - 1) / 2), chartSeries.length - 1]);
  const categories = activeTab === 'inventory' ? report?.inventory_categories ?? [] : activeTab === 'purchases' ? report?.purchase_categories ?? [] : report?.categories ?? [];
  const chartData = activeTab === 'inventory'
    ? categories.map((category) => ({ label: category.name, primary: Number(category.revenue), secondary: 0, tertiary: 0, quaternary: 0, netResult: 0 }))
    : chartSeries.map((day) => ({ label: day.label, primary: activeTab === 'purchases' ? day.purchases : day.revenue, secondary: activeTab === 'financial' ? day.cost_of_goods : activeTab === 'sales' ? day.gross_profit : 0, tertiary: activeTab === 'financial' ? day.expenses : 0, quaternary: 0, netResult: activeTab === 'financial' ? day.net_profit : 0 }));
  const maxValue = Math.max(...chartData.flatMap((day) => [day.primary, day.secondary, day.tertiary, day.quaternary, Math.abs(day.netResult)]), 1);
  const categoryTotal = categories.reduce((sum, category) => sum + category.percent, 0);
  let accumulatedPercent = 0;
  const donutGradient = categories.length ? `conic-gradient(${categories.map((category, index) => {
    const start = accumulatedPercent;
    accumulatedPercent += category.percent;
    return `${palette[index % palette.length]} ${start}% ${accumulatedPercent}%`;
  }).join(', ')})` : '#e7edf5';

  const metricCards = report ? activeTab === 'inventory' ? [
    { label: 'INVENTORY VALUE', value: currency(report.inventory_value), detail: 'Valued at current cost', icon: Boxes, tone: 'blue' },
    { label: 'UNITS ON HAND', value: report.inventory_units.toLocaleString(), detail: `${report.total_skus} active SKUs`, icon: Package, tone: 'green' },
    { label: 'STOCK ALERTS', value: (report.low_stock_count + report.out_of_stock_count).toLocaleString(), detail: `${report.out_of_stock_count} out of stock`, icon: TrendingUp, tone: 'amber' },
    { label: 'INVENTORY TURNOVER', value: `${report.inventory_turnover}×`, detail: 'Annualized at cost', icon: RefreshCw, tone: 'mint' },
  ] : activeTab === 'purchases' ? [
    { label: 'RECEIVED SPEND', value: currency(report.purchase_spend), detail: 'In selected period', icon: Truck, tone: 'blue' },
    { label: 'ORDERS RECEIVED', value: report.received_orders.toLocaleString(), detail: 'Completed supplier orders', icon: ShoppingCart, tone: 'green' },
    { label: 'OPEN ORDERS', value: report.open_orders.toLocaleString(), detail: `${currency(report.open_purchase_value)} committed`, icon: BriefcaseBusiness, tone: 'amber' },
    { label: 'PURCHASE CATEGORIES', value: categories.length.toLocaleString(), detail: 'With received units', icon: Boxes, tone: 'mint' },
  ] : [
    { label: 'NET REVENUE', value: currency(report.revenue), detail: `${report.revenue_change_percent >= 0 ? '+' : ''}${report.revenue_change_percent}% vs previous period`, icon: ChartNoAxesCombined, tone: 'blue' },
    { label: 'COST OF GOODS', value: currency(report.cost_of_goods), detail: 'Cost snapshots at checkout', icon: ShoppingCart, tone: 'slate' },
    { label: Number(report.gross_profit) < 0 ? 'GROSS LOSS' : 'GROSS PROFIT', value: currency(report.gross_profit), detail: `${report.gross_margin}% gross margin`, icon: TrendingUp, tone: Number(report.gross_profit) < 0 ? 'loss' : 'green' },
    { label: activeTab === 'financial' ? Number(report.net_profit) < 0 ? 'NET LOSS' : 'NET PROFIT' : 'INVENTORY TURNOVER', value: activeTab === 'financial' ? currency(report.net_profit) : `${report.inventory_turnover}×`, detail: activeTab === 'financial' ? `${currency(report.operating_expenses)} operating expenses` : 'Annualized at cost', icon: activeTab === 'financial' ? BriefcaseBusiness : RefreshCw, tone: activeTab === 'financial' && Number(report.net_profit) < 0 ? 'loss' : 'mint' },
  ] : [];

  function exportReport() {
    if (activeTab === 'balance-sheet') {
      if (!balanceSheet) return;
      const csv = balanceSheetExportRows(balanceSheet).map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\r\n');
      const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = `stockpulse-balance-sheet-${balanceSheet.as_of_date}.csv`;
      link.click();
      URL.revokeObjectURL(url);
      return;
    }
    if (!report) return;
    const rows = activeTab === 'inventory'
      ? [['Category', 'Units on hand', 'Inventory value', 'Mix %'], ...report.inventory_categories.map((category) => [category.name, category.units, category.revenue, `${category.percent}%`])]
      : activeTab === 'purchases'
        ? [['Category', 'Units received', 'Purchase spend', 'Mix %'], ...report.purchase_categories.map((category) => [category.name, category.units, category.revenue, `${category.percent}%`])]
        : activeTab === 'financial'
          ? [['Profit & loss metric', 'Amount'], ['Sales revenue', report.revenue], ['Less: cost of goods sold', report.cost_of_goods], ['Gross profit/loss', report.gross_profit], ['Less: operating expenses', report.operating_expenses], [Number(report.net_profit) < 0 ? 'Net loss' : 'Net profit', report.net_profit]]
          : [['Product', 'SKU', 'Category', 'Units sold', 'Revenue', 'Cost', 'Gross profit', 'Gross margin', 'Average price'], ...report.top_products.map((product) => [product.product_name, product.product_sku, product.category_name, product.units_sold, product.revenue, product.cost, product.gross_profit, `${product.gross_margin}%`, product.average_price])];
    const csv = rows.map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `stockpulse-report-${dayMode ? selectedDate : monthMode ? selectedMonth : range}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function exportReportPdf() {
    if (activeTab === 'balance-sheet') {
      if (!balanceSheet) return;
      const [{ jsPDF }, { default: autoTable }] = await Promise.all([import('jspdf'), import('jspdf-autotable')]);
      const document = new jsPDF({ orientation: 'portrait', unit: 'pt', format: 'a4' });
      const rows = balanceSheetExportRows(balanceSheet).slice(3);
      document.setFontSize(17);
      document.text('StockPulse · Balance sheet', 36, 40);
      document.setFontSize(9);
      document.text(`As of ${dateLabel(balanceSheet.as_of_date)} · Amounts in ${getCurrencyDisplay().currency}`, 36, 58);
      autoTable(document, {
        head: [['Section', 'Account', 'Current balance']],
        body: rows.map(([section, account, amount]) => [
          section,
          account,
          amount === '' || amount === '—' ? amount : currency(amount),
        ]),
        startY: 76,
        styles: { fontSize: 8, cellPadding: 5 },
        headStyles: { fillColor: [40, 101, 233] },
        margin: { left: 36, right: 36 },
      });
      document.save(`stockpulse-balance-sheet-${balanceSheet.as_of_date}.pdf`);
      return;
    }
    if (!report) return;
    const [{ jsPDF }, { default: autoTable }] = await Promise.all([import('jspdf'), import('jspdf-autotable')]);
    const title = reportTabs.find((tab) => tab.value === activeTab)?.label ?? 'Business report';
    const headings = activeTab === 'inventory'
      ? ['Category', 'Units on hand', 'Inventory value', 'Mix %']
      : activeTab === 'purchases'
        ? ['Category', 'Units received', 'Purchase spend', 'Mix %']
        : activeTab === 'financial' ? ['Profit & loss metric', 'Amount'] : ['Product', 'SKU', 'Category', 'Units sold', 'Revenue', 'Cost', 'Gross profit', 'Gross margin', 'Average price'];
    const body = activeTab === 'inventory'
      ? report.inventory_categories.map((category) => [category.name, category.units.toLocaleString(), currency(category.revenue), `${category.percent}%`])
      : activeTab === 'purchases'
        ? report.purchase_categories.map((category) => [category.name, category.units.toLocaleString(), currency(category.revenue), `${category.percent}%`])
        : activeTab === 'financial'
          ? [['Sales revenue', report.revenue], ['Less: cost of goods sold', report.cost_of_goods], ['Gross profit/loss', report.gross_profit], ['Less: operating expenses', report.operating_expenses], [Number(report.net_profit) < 0 ? 'Net loss' : 'Net profit', report.net_profit]].map(([label, amount]) => [label, currency(amount)])
          : report.top_products.map((product) => [product.product_name, product.product_sku, product.category_name, product.units_sold.toLocaleString(), currency(product.revenue), currency(product.cost), currency(product.gross_profit), `${product.gross_margin}%`, currency(product.average_price)]);
    const document = new jsPDF({ orientation: 'landscape', unit: 'pt', format: 'a4' });
    document.setFontSize(17);
    document.text(`StockPulse · ${title}`, 36, 40);
    document.setFontSize(9);
    document.text(`${dateLabel(report.start_date)} - ${dateLabel(report.end_date)} · Amounts in ${getCurrencyDisplay().currency}`, 36, 58);
    autoTable(document, {
      head: [headings],
      body,
      startY: 76,
      styles: { fontSize: 8, cellPadding: 5 },
      headStyles: { fillColor: [40, 101, 233] },
      margin: { left: 36, right: 36 },
    });
    document.save(`stockpulse-${activeTab}-report-${dayMode ? selectedDate : monthMode ? selectedMonth : range}.pdf`);
  }

  return <>
    <section className="catalog-heading reports-heading"><div><div className="catalog-breadcrumb">Analytics <span>›</span> <b>Business reports</b></div><h1>Analytics &amp; Business Reports</h1><p>Track revenue, margin, stock value, supplier spend, and financial position.</p></div><div className="reports-heading-actions"><span className="reports-live"><i/>Live</span>{activeTab !== 'balance-sheet' && <div className="overview-flow-controls"><label className="catalog-select reports-range"><select aria-label="Report history range" value={dayMode ? 'day' : monthMode ? 'month' : range} onChange={(event) => { if (event.target.value === 'day') { setDayMode(true); setMonthMode(false); } else if (event.target.value === 'month') { setMonthMode(true); setDayMode(false); } else { setMonthMode(false); setDayMode(false); setRange(event.target.value as DateRange); } }}><optgroup label="Rolling history"><option value="1d">Last day</option><option value="7d">Last week</option><option value="30d">Last month</option><option value="90d">Last 3 months</option><option value="180d">Last 6 months</option><option value="365d">Last year</option><option value="730d">Last 2 years</option><option value="1825d">Last 5 years</option><option value="3650d">Last 10 years</option><option value="18250d">Last 50 years</option><option value="36500d">Last 100 years</option><option value="73000d">Last 200 years</option></optgroup><option value="day">Choose a day</option><option value="month">Choose month &amp; year</option></select></label>{dayMode && <input className="overview-flow-month-picker" type="date" aria-label="Select report day" value={selectedDate} onChange={(event) => setSelectedDate(event.target.value)}/>}{monthMode && <input className="overview-flow-month-picker" type="month" aria-label="Select report month and year" value={selectedMonth} onChange={(event) => setSelectedMonth(event.target.value)}/>}</div>}<FileActionMenu label="Export" direction="export" options={[{ label: 'CSV report', onSelect: exportReport, disabled: activeTab === 'balance-sheet' ? !balanceSheet : !report }, { label: 'PDF report', onSelect: () => void exportReportPdf().catch((cause: unknown) => { const message = cause instanceof Error ? cause.message : 'PDF export failed.'; if (activeTab === 'balance-sheet') setBalanceSheetError(message); else setError(message); }), disabled: activeTab === 'balance-sheet' ? !balanceSheet : !report }]}/></div></section>
    <div className="reports-tabs" role="tablist" aria-label="Report types">{reportTabs.map(({ value, label, icon: Icon }) => <button key={value} role="tab" aria-selected={activeTab === value} className={activeTab === value ? 'active' : ''} onClick={() => setActiveTab(value)}><Icon size={14}/>{label}</button>)}</div>
    <div className="reports-filter-row"><span>{activeTab === 'balance-sheet' ? balanceSheet ? `As of ${dateLabel(balanceSheet.as_of_date)}` : 'Current financial position' : report ? `${dateLabel(report.start_date)} – ${dateLabel(report.end_date)}` : 'Selected period'}</span>{activeTab !== 'balance-sheet' && <div><span>VIEW:</span><button className="active">By category</button><button onClick={onOpenInventory}>Inventory</button>{activeTab === 'financial' && <button onClick={onOpenExpenses}>Expenses</button>}</div>}</div>
    {activeTab === 'balance-sheet' && balanceSheetLoading && <section className="overview-state">Loading balance sheet…</section>}
    {activeTab === 'balance-sheet' && !balanceSheetLoading && balanceSheetError && <section className="overview-state overview-error"><strong>Could not load balance sheet</strong><span>{balanceSheetError}</span><button className="catalog-button catalog-button-light" onClick={() => void loadBalanceSheet()}><RefreshCw size={14}/>Retry</button></section>}
    {activeTab === 'balance-sheet' && !balanceSheetLoading && balanceSheet && <BalanceSheetReport sheet={balanceSheet} onRefresh={loadBalanceSheet}/>}
    {loading && activeTab !== 'balance-sheet' && <section className="overview-state">Loading reports from the API…</section>}
    {!loading && error && activeTab !== 'balance-sheet' && <section className="overview-state overview-error"><strong>Could not load reports</strong><span>{error}</span><button className="catalog-button catalog-button-light" onClick={() => void loadReport(range, monthMode ? selectedMonth : undefined, dayMode ? selectedDate : undefined)}><RefreshCw size={14}/>Retry</button></section>}
    {!loading && report && activeTab !== 'balance-sheet' && <>
      <section className="reports-metrics" aria-label="Report metrics">{metricCards.map(({ label, value, detail, icon: Icon, tone }) => <article className={`reports-metric ${tone}`} key={label}><div><span>{label}</span><Icon size={15}/></div><strong>{value}</strong><small>{detail}</small></article>)}</section>
      {activeTab === 'financial' && <section className="overview-panel reports-pnl-panel" aria-label="Profit and loss calculation">
        <div className="overview-panel-heading"><div><span>SELECTED PERIOD</span><h2>How your profit or loss is calculated</h2></div></div>
        <div className="reports-pnl-rows">
          <div><span>Sales revenue</span><strong>{currency(report.revenue)}</strong></div>
          <div><span>Less: cost of goods sold</span><strong>− {currency(report.cost_of_goods)}</strong></div>
          <div className="reports-pnl-subtotal"><span>Gross profit / loss</span><strong>{currency(report.gross_profit)}</strong></div>
          <div><span>Less: operating expenses</span><strong>− {currency(report.operating_expenses)}</strong></div>
          <div className={`reports-pnl-result ${Number(report.net_profit) < 0 ? 'is-loss' : 'is-profit'}`}><span>{Number(report.net_profit) < 0 ? 'NET LOSS' : 'NET PROFIT'}</span><strong>{currency(report.net_profit)}</strong></div>
        </div>
        <p>Net result = sales revenue − cost of goods sold − approved or paid operating expenses for this period.</p>
      </section>}
      <div className="reports-analysis-grid">
        <section className="overview-panel reports-chart-panel"><div className="overview-panel-heading"><div><span>{activeTab === 'inventory' ? 'STOCK HEALTH' : activeTab === 'purchases' ? 'SUPPLIER ACTIVITY' : 'PERFORMANCE'}</span><h2>{activeTab === 'inventory' ? 'Inventory value by category' : activeTab === 'purchases' ? 'Purchase spend trend' : activeTab === 'financial' ? 'Profit & loss, revenue trend' : 'Revenue & gross profit trend'}</h2></div><span className="overview-period">{monthMode ? 'Daily totals' : report.series_interval === 'year' ? 'Yearly totals' : report.series_interval === 'month' || range === '365d' ? 'Monthly totals' : range === '90d' || range === '180d' ? 'Weekly totals' : 'Daily totals'}</span></div>
          <div className="reports-chart-legend">{activeTab === 'inventory' ? <span><i className="inventory-legend"/>Inventory value</span> : activeTab === 'purchases' ? <span><i className="purchase-legend"/>Received spend</span> : activeTab === 'financial' ? <><span><i className="revenue-legend"/>Sales revenue</span><span><i className="purchase-legend"/>Cost of goods</span><span><i className="expense-legend"/>Operating expenses</span><span><i className="net-legend"/>Net profit</span><span><i className="loss-legend"/>Net loss</span></> : <><span><i className="revenue-legend"/>Revenue</span><span><i className="profit-legend"/>Gross profit</span></>}</div>
          <div className={`reports-chart ${activeTab === 'inventory' ? 'category-chart' : ''}`} role="img" aria-label={`${activeTab === 'inventory' ? 'Category inventory valuation' : `${report.range_days}-day ${activeTab} report trend`}`}>
            {chartData.map((day) => <div className="reports-chart-day" key={day.label} title={`${day.label}: ${currency(day.primary)}`}>
              <div className={`reports-chart-bars ${activeTab === 'financial' ? 'financial-chart-bars' : ''}`}>
                <i className={activeTab === 'inventory' ? 'inventory-bar' : activeTab === 'purchases' ? 'purchase-bar' : 'revenue-bar'} style={{ height: `${day.primary ? Math.max(day.primary / maxValue * 100, 2) : 0}%` }}/>
                {day.secondary > 0 && <i className={activeTab === 'financial' ? 'purchase-bar' : 'profit-bar'} style={{ height: `${Math.max(day.secondary / maxValue * 100, 2)}%` }}/>}
                {day.tertiary > 0 && <i className={activeTab === 'financial' ? 'expense-bar' : 'purchase-bar'} style={{ height: `${Math.max(day.tertiary / maxValue * 100, 2)}%` }}/>}
                {day.quaternary > 0 && <i className="expense-bar" style={{ height: `${Math.max(day.quaternary / maxValue * 100, 2)}%` }}/>}
                {day.netResult !== 0 && <i className={day.netResult < 0 ? 'net-loss-bar' : 'net-profit-bar'} title={`${day.netResult < 0 ? 'Net loss' : 'Net profit'}: ${currency(day.netResult)}`} style={{ height: `${Math.max(Math.abs(day.netResult) / maxValue * 100, 2)}%` }}/>}
              </div>
            </div>)}
          </div>
          <div className="reports-chart-labels">{chartData.map((day, index) => <span key={day.label}>{activeTab === 'inventory' ? day.label : labelIndexes.has(index) ? day.label : ''}</span>)}</div>
        </section>
        <section className="overview-panel reports-category-panel"><div className="overview-panel-heading"><div><span>CATEGORY MIX</span><h2>{activeTab === 'inventory' ? 'Stock value' : activeTab === 'purchases' ? 'Received spend' : 'Sales distribution'}</h2></div><button className="overview-text-action" onClick={activeTab === 'purchases' ? onOpenPurchases : activeTab === 'inventory' ? onOpenInventory : onOpenPOS}>Details</button></div>
          <div className="reports-donut-wrap"><div className="reports-donut" style={{ background: donutGradient }}><div><small>{activeTab === 'inventory' ? 'AT COST' : activeTab === 'purchases' ? 'RECEIVED' : 'NET SALES'}</small><strong>{currency(activeTab === 'inventory' ? report.inventory_value : activeTab === 'purchases' ? report.purchase_spend : report.revenue)}</strong></div></div></div>
          {categories.length ? <div className="reports-category-list">{categories.slice(0, 5).map((category, index) => <div key={category.name}><span><i style={{ backgroundColor: palette[index % palette.length] }}/>{category.name}</span><strong>{currency(category.revenue)}</strong><small>{category.percent}%</small></div>)}</div> : <p className="overview-empty">No category activity in this period.</p>}
          {categoryTotal > 0 && <span className="reports-category-total">{categories.length} categories · 100% of period total</span>}
        </section>
      </div>
      <section className="catalog-table-panel reports-products-panel"><div className="reports-table-heading"><div><span>PRODUCT PERFORMANCE</span><h2>Top products by revenue</h2></div><button className="catalog-button catalog-button-light" onClick={onOpenInventory}><Package size={13}/>Inventory</button></div><div className="catalog-table-scroll"><table className="catalog-table reports-products-table"><thead><tr><th>#</th><th>PRODUCT</th><th>SKU</th><th>UNITS SOLD</th><th>AVG. PRICE</th><th>REVENUE</th><th>GROSS PROFIT</th><th>MARGIN</th></tr></thead><tbody>{report.top_products.slice(0, 8).map((product, index) => <tr key={product.product_sku}><td className="reports-rank">{String(index + 1).padStart(2, '0')}</td><td><strong>{product.product_name}</strong><small className="reports-category-name">{product.category_name}</small></td><td>{product.product_sku}</td><td>{product.units_sold.toLocaleString()}</td><td>{currency(product.average_price)}</td><td><strong>{currency(product.revenue)}</strong></td><td>{currency(product.gross_profit)}</td><td><span className="reports-margin">{product.gross_margin}%</span></td></tr>)}{!report.top_products.length && <tr><td colSpan={8} className="catalog-state">No completed sales in this period yet.</td></tr>}</tbody></table></div><footer className="catalog-table-footer"><span>Showing <b>{report.top_products.length}</b> top products for this period</span></footer></section>
    </>}
  </>;
}
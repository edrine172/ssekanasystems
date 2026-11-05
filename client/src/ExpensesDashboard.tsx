import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUpRight, Check, ChevronDown, CircleAlert, Landmark, Pencil, Plus, ReceiptText, RefreshCw, Search, Settings2, ShieldCheck, Trash2, Wallet, X } from 'lucide-react';
import { api, formatCurrency as currency, type BalanceSheetCategory, type BalanceSheetSection, type BalanceSheetSummary, type Expense, type ExpenseBudget, type ExpenseCategoryOption, type ExpenseInput, type ExpenseOptions, type ExpenseSummary, type ExpenseTypeOption } from './api';
import { downloadSpreadsheet, readSpreadsheetRows } from './fileFormats';
import FileActionMenu from './FileActionMenu';

type ExpenseTrend = string;
type ReceiptFilter = 'all' | 'verified' | 'missing';
const localDate = () => {
  const today = new Date();
  return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
};
function ExpenseForm({ categories, types, onClose, onSaved }: {
  categories: ExpenseCategoryOption[];
  types: ExpenseTypeOption[];
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [draft, setDraft] = useState({
    merchant: '', description: '', category: categories[0]?.name ?? '', cost_center: '',
    expense_type: types[0]?.value ?? '', amount_before_tax: '', tax_amount: '0.00',
    payment_method: 'bank' as ExpenseInput['payment_method'], status: 'pending' as ExpenseInput['status'],
    reference: '', expense_date: localDate(), receipt_received: false,
    receipt_verified: false, entered_by: 'Elena Vance',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const total = Number(draft.amount_before_tax || 0) + Number(draft.tax_amount || 0);
  const update = (key: keyof typeof draft, value: string | boolean) => setDraft((current) => ({ ...current, [key]: value }));

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError('');
    try {
      await api.createExpense({ ...draft, amount_before_tax: draft.amount_before_tax, tax_amount: draft.tax_amount, receipt_verified: draft.receipt_received && draft.receipt_verified });
      await onSaved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not record this expense.');
    } finally {
      setSaving(false);
    }
  }

  return <div className="catalog-overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><form className="catalog-modal expense-form-modal" onSubmit={submit}>
    <div className="catalog-modal-heading"><div><span className="catalog-eyebrow">FINANCE &amp; ACCOUNTING</span><h2>Record expense</h2><p>Capture vendor spend, tax, receipt, and approval details.</p></div><button className="catalog-icon-button" type="button" onClick={onClose} aria-label="Close"><X size={18}/></button></div>
    <div className="catalog-form-row"><label className="catalog-field">Merchant<input required maxLength={160} value={draft.merchant} onChange={(event) => update('merchant', event.target.value)} placeholder="Vendor or merchant name"/></label><label className="catalog-field">Expense date<input required type="date" value={draft.expense_date} onChange={(event) => update('expense_date', event.target.value)}/></label></div>
    <label className="catalog-field">Description<input required maxLength={240} value={draft.description} onChange={(event) => update('description', event.target.value)} placeholder="What was purchased or paid for?"/></label>
    <div className="catalog-form-row"><label className="catalog-field">Category<select required value={draft.category} onChange={(event) => update('category', event.target.value)}>{categories.map((category) => <option key={category.id} value={category.name}>{category.name}</option>)}</select></label><label className="catalog-field">Cost center<input maxLength={80} value={draft.cost_center} onChange={(event) => update('cost_center', event.target.value)} placeholder="Warehouse & Logistics"/></label></div>
    <div className="catalog-form-row"><label className="catalog-field">Expense type<select required value={draft.expense_type} onChange={(event) => update('expense_type', event.target.value)}>{types.map((type) => <option key={type.id} value={type.value}>{type.label}</option>)}</select></label><label className="catalog-field">Payment method<select value={draft.payment_method} onChange={(event) => update('payment_method', event.target.value as ExpenseInput['payment_method'])}><option value="bank">ACH / wire</option><option value="card">Card</option><option value="cash">Cash</option><option value="check">Check</option><option value="petty_cash">Petty cash</option></select></label></div>
    <div className="catalog-form-row"><label className="catalog-field">Amount before tax<input type="number" min="0.01" step="0.01" required value={draft.amount_before_tax} onChange={(event) => update('amount_before_tax', event.target.value)}/></label><label className="catalog-field">Tax amount<input type="number" min="0" step="0.01" value={draft.tax_amount} onChange={(event) => update('tax_amount', event.target.value)}/></label></div>
    <div className="catalog-form-row"><label className="catalog-field">Voucher / invoice reference<input maxLength={80} value={draft.reference} onChange={(event) => update('reference', event.target.value)}/></label><label className="catalog-field">Approval status<select value={draft.status} onChange={(event) => update('status', event.target.value as ExpenseInput['status'])}><option value="pending">Pending approval</option><option value="approved">Approved</option><option value="paid">Paid</option></select></label></div>
    <div className="expense-receipt-options"><label><input type="checkbox" checked={draft.receipt_received} onChange={(event) => { update('receipt_received', event.target.checked); if (!event.target.checked) update('receipt_verified', false); }}/>Receipt received</label><label><input type="checkbox" disabled={!draft.receipt_received} checked={draft.receipt_verified} onChange={(event) => update('receipt_verified', event.target.checked)}/>Receipt verified</label><strong>Total {currency(total)}</strong></div>
    {error && <p className="catalog-form-error">{error}</p>}
    <div className="catalog-modal-actions"><button type="button" className="catalog-button catalog-button-light" onClick={onClose}>Cancel</button><button className="catalog-button catalog-button-primary" disabled={saving}>{saving ? 'Saving…' : 'Record expense'}</button></div>
  </form></div>;
}

function ExpenseOptionsForm({ categories, types, onClose, onAdd, onDeleteCategory, onDeleteType }: {
  categories: ExpenseCategoryOption[];
  types: ExpenseTypeOption[];
  onClose: () => void;
  onAdd: (kind: 'category' | 'type', name: string) => Promise<void>;
  onDeleteCategory: (category: ExpenseCategoryOption) => Promise<void>;
  onDeleteType: (type: ExpenseTypeOption) => Promise<void>;
}) {
  const [categoryName, setCategoryName] = useState('');
  const [typeName, setTypeName] = useState('');
  const [saving, setSaving] = useState<'category' | 'type' | null>(null);
  const [deletingOption, setDeletingOption] = useState<{ kind: 'category' | 'type'; id: number } | null>(null);
  const [error, setError] = useState('');

  async function addOption(kind: 'category' | 'type') {
    const name = (kind === 'category' ? categoryName : typeName).trim();
    if (!name) {
      setError(`Enter an expense ${kind} name.`);
      return;
    }
    setSaving(kind);
    setError('');
    try {
      await onAdd(kind, name);
      if (kind === 'category') setCategoryName('');
      else setTypeName('');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : `Could not add this expense ${kind}.`);
    } finally {
      setSaving(null);
    }
  }

  async function deleteCategory(category: ExpenseCategoryOption) {
    setDeletingOption({ kind: 'category', id: category.id });
    setError('');
    try {
      await onDeleteCategory(category);
    } catch (cause) {
      if (cause instanceof Error && cause.message === 'Action cancelled.') return;
      setError(cause instanceof Error ? cause.message : `Could not delete ${category.name}.`);
    } finally {
      setDeletingOption(null);
    }
  }

  async function deleteType(type: ExpenseTypeOption) {
    setDeletingOption({ kind: 'type', id: type.id });
    setError('');
    try {
      await onDeleteType(type);
    } catch (cause) {
      if (cause instanceof Error && cause.message === 'Action cancelled.') return;
      setError(cause instanceof Error ? cause.message : `Could not delete ${type.label}.`);
    } finally {
      setDeletingOption(null);
    }
  }

  return <div className="catalog-overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="catalog-modal expense-options-modal" role="dialog" aria-modal="true" aria-labelledby="expense-options-title">
    <div className="catalog-modal-heading"><div><span className="catalog-eyebrow">EXPENSE SETTINGS</span><h2 id="expense-options-title">Manage expense options</h2><p>Control the categories and types available when recording expenses.</p></div><button className="catalog-icon-button" type="button" onClick={onClose} aria-label="Close expense settings"><X size={18}/></button></div>
    <section className="expense-option-editor" aria-labelledby="expense-categories-title">
      <div className="expense-option-section-heading"><div><h3 id="expense-categories-title">Expense categories</h3><p>Past expenses and budgets are kept when a category is removed.</p></div><span className="expense-option-count">{categories.length} {categories.length === 1 ? 'category' : 'categories'}</span></div>
      <div className="catalog-form-row"><label className="catalog-field">Add a category<input maxLength={80} value={categoryName} onChange={(event) => setCategoryName(event.target.value)} placeholder="e.g. Marketing"/></label><button className="catalog-button catalog-button-primary" type="button" disabled={saving !== null || deletingOption !== null} onClick={() => void addOption('category')}><Plus size={14}/>{saving === 'category' ? 'Adding…' : 'Add category'}</button></div>
      <div className="expense-option-list" role="list" aria-label="Current expense categories">{categories.map((category) => <div className="expense-option-row" role="listitem" key={category.id}><span className="expense-option-name">{category.name}</span><button type="button" className="expense-option-delete" disabled={saving !== null || deletingOption !== null} onClick={() => void deleteCategory(category)} aria-label={`Delete ${category.name} category`}>{deletingOption?.kind === 'category' && deletingOption.id === category.id ? <RefreshCw size={14} className="expense-option-spinner"/> : <Trash2 size={14}/>}<span>{deletingOption?.kind === 'category' && deletingOption.id === category.id ? 'Deleting…' : 'Delete'}</span></button></div>)}</div>
      {!categories.length && <p className="expense-option-empty">No categories yet. Add one to use it on new expenses.</p>}
    </section>
    <section className="expense-option-editor expense-type-editor" aria-labelledby="expense-types-title">
      <div className="expense-option-section-heading"><div><h3 id="expense-types-title">Expense types</h3><p>Use types to classify and compare spending.</p></div><span className="expense-option-count">{types.length} {types.length === 1 ? 'type' : 'types'}</span></div>
      <div className="catalog-form-row"><label className="catalog-field">Add an expense type<input maxLength={80} value={typeName} onChange={(event) => setTypeName(event.target.value)} placeholder="e.g. Travel"/></label><button className="catalog-button catalog-button-primary" type="button" disabled={saving !== null || deletingOption !== null} onClick={() => void addOption('type')}><Plus size={14}/>{saving === 'type' ? 'Adding…' : 'Add type'}</button></div>
      <div className="expense-option-list" role="list" aria-label="Current expense types">{types.map((type) => <div className="expense-option-row" role="listitem" key={type.id}><span className="expense-option-name">{type.label}</span><button type="button" className="expense-option-delete" disabled={saving !== null || deletingOption !== null} onClick={() => void deleteType(type)} aria-label={`Delete ${type.label} expense type`}>{deletingOption?.kind === 'type' && deletingOption.id === type.id ? <RefreshCw size={14} className="expense-option-spinner"/> : <Trash2 size={14}/>}<span>{deletingOption?.kind === 'type' && deletingOption.id === type.id ? 'Deleting…' : 'Delete'}</span></button></div>)}</div>
      {!types.length && <p className="expense-option-empty">No expense types are available.</p>}
    </section>
    {error && <p className="catalog-form-error">{error}</p>}
    <div className="catalog-modal-actions"><button type="button" className="catalog-button catalog-button-light" onClick={onClose}>Done</button></div>
  </section></div>;
}

function BudgetForm({ initial, onClose, onSaved }: {
  initial: ExpenseBudget | null;
  onClose: () => void;
  onSaved: (budget: Pick<ExpenseBudget, 'category' | 'monthly_limit' | 'cost_center' | 'manager'>) => Promise<void>;
}) {
  const [category, setCategory] = useState(initial?.category ?? '');
  const [monthlyLimit, setMonthlyLimit] = useState(initial?.monthly_limit ?? '');
  const [costCenter, setCostCenter] = useState(initial?.cost_center ?? '');
  const [manager, setManager] = useState(initial?.manager ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try { await onSaved({ category, monthly_limit: monthlyLimit, cost_center: costCenter, manager }); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not save this budget.'); }
    finally { setSaving(false); }
  }
  return <div className="catalog-overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><form className="catalog-modal expense-budget-modal" onSubmit={submit}>
    <div className="catalog-modal-heading"><div><span className="catalog-eyebrow">BUDGET GUARDRAILS</span><h2>{initial ? 'Update category budget' : 'Set category budget'}</h2><p>Monthly spend limits help flag overages early.</p></div><button className="catalog-icon-button" type="button" onClick={onClose} aria-label="Close"><X size={18}/></button></div>
    <label className="catalog-field">Category<input required maxLength={80} value={category} onChange={(event) => setCategory(event.target.value)} disabled={Boolean(initial)}/></label>
    <label className="catalog-field">Monthly budget<input required type="number" min="0.01" step="0.01" value={monthlyLimit} onChange={(event) => setMonthlyLimit(event.target.value)}/></label>
    <div className="catalog-form-row"><label className="catalog-field">Cost center<input maxLength={80} value={costCenter} onChange={(event) => setCostCenter(event.target.value)}/></label><label className="catalog-field">Budget owner<input maxLength={120} value={manager} onChange={(event) => setManager(event.target.value)}/></label></div>
    {error && <p className="catalog-form-error">{error}</p>}
    <div className="catalog-modal-actions"><button type="button" className="catalog-button catalog-button-light" onClick={onClose}>Cancel</button><button className="catalog-button catalog-button-primary" disabled={saving}>{saving ? 'Saving…' : 'Save budget'}</button></div>
  </form></div>;
}

function BalanceSheetPanel() {
  const [sheet, setSheet] = useState<BalanceSheetSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<{ category: BalanceSheetCategory; name: string; current_amount: string | null; manual_current_amount: string | null; source: string; editable_current: boolean } | null>(null);
  const [currentAmount, setCurrentAmount] = useState('');

  async function loadSheet() {
    setLoading(true);
    setError('');
    try { setSheet(await api.balanceSheet()); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'The balance sheet could not be loaded.'); }
    finally { setLoading(false); }
  }

  useEffect(() => { void loadSheet(); }, []);

  function startEdit(account: NonNullable<typeof editing>) {
    setEditing(account);
    setCurrentAmount(account.manual_current_amount ?? '');
    setShowForm(true);
    setError('');
  }

  async function saveAccount(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing) return;
    setSaving(true);
    setError('');
    try {
      const input = { amount: currentAmount };
      await api.updateBalanceSheetAccount(editing.category, input);
      setShowForm(false);
      setNotice('Balance sheet account saved.');
      await loadSheet();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save this account balance.');
    } finally {
      setSaving(false);
    }
  }

  const sections: Array<{ key: 'assets' | 'liabilities' | 'equity'; title: string; total: string; section: BalanceSheetSection }> = sheet ? [
    { key: 'assets', title: 'Assets', total: sheet.total_assets, section: sheet.assets },
    { key: 'liabilities', title: 'Liabilities', total: sheet.total_liabilities, section: sheet.liabilities },
    { key: 'equity', title: "Shareholders’ equity", total: sheet.total_equity, section: sheet.equity },
  ] : [];
  const formatBalance = (amount: string | null) => amount === null ? '—' : currency(amount);

  return <section className="overview-panel expense-balance-panel">
    <div className="overview-panel-heading">
      <div><span>FINANCIAL POSITION</span><h2>Balance sheet</h2></div>
      <div className="expense-balance-heading-actions">
        {sheet && <span>As of {new Date(`${sheet.as_of_date}T00:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</span>}
      </div>
    </div>
    <p className="expense-balance-note">Current inventory, receivables, payables, and approved unpaid expenses are linked automatically. Enter the remaining current balances. Verify manually entered amounts against your accounting records.</p>
    {loading && <div className="catalog-state">Loading balance sheet…</div>}
    {!loading && error && !sheet && <div className="overview-state overview-error"><strong>Could not load balance sheet</strong><span>{error}</span><button className="catalog-button catalog-button-light" type="button" onClick={() => void loadSheet()}><RefreshCw size={13}/>Retry</button></div>}
    {!loading && sheet && <>
      <div className={`expense-balance-status ${sheet.is_balanced ? 'balanced' : 'unbalanced'}`}>
        <strong>{!sheet.current_complete ? 'Current year incomplete' : sheet.is_balanced ? 'Current year balanced' : 'Current year out of balance'}</strong>
        <span>{!sheet.current_complete ? 'Enter a current balance for every category to check the totals.' : sheet.is_balanced ? 'Assets equal liabilities plus equity.' : `Difference: ${currency(sheet.difference)}`}</span>
      </div>
      {error && <div className="expense-inline-error"><CircleAlert size={13}/>{error}</div>}
      {notice && <div className="expense-balance-notice"><Check size={13}/>{notice}<button type="button" onClick={() => setNotice('')} aria-label="Dismiss"><X size={12}/></button></div>}
      <div className="expense-balance-sections">{sections.map((section) => <section key={section.key} className="expense-balance-section">
        <div className="expense-balance-section-heading"><h3>{section.title}</h3><strong>{section.section.current_complete ? currency(section.total) : '—'}</strong></div>
        <div className="expense-balance-year-heading"><span></span><strong>{sheet.current_year}</strong><span></span></div>
        {section.section.groups.map((group) => <div className="expense-balance-group" key={group.title}>
          <div className="expense-balance-group-heading"><strong>{group.title}</strong><span>{group.current_complete ? currency(group.current_total) : '—'}</span></div>
          {group.rows.map((row) => <div className="expense-balance-row" key={row.category}>
            <div><strong>{row.name}</strong><small>{row.source}</small></div>
            <strong>{formatBalance(row.current_amount)}</strong>
            {row.editable_current && <button type="button" className="catalog-icon-button" onClick={() => startEdit(row)} aria-label={`Edit ${row.name} balance`}><Pencil size={12}/></button>}
          </div>)}
        </div>)}
      </section>)}</div>
      <div className="expense-balance-totals">
        {[{ label: 'Total assets', section: sheet.assets, current: sheet.total_assets }, { label: 'Total liabilities', section: sheet.liabilities, current: sheet.total_liabilities }, { label: 'Total shareholders’ equity', section: sheet.equity, current: sheet.total_equity }].map((total) => <div key={total.label}><span>{total.label}</span><strong>{total.section.current_complete ? currency(total.current) : '—'}</strong></div>)}
        <div><span>Total liabilities and shareholders’ equity</span><strong>{sheet.liabilities.current_complete && sheet.equity.current_complete ? currency(Number(sheet.total_liabilities) + Number(sheet.total_equity)) : '—'}</strong></div>
      </div>
    </>}
    {showForm && editing && <div className="catalog-overlay" onMouseDown={(event) => event.target === event.currentTarget && setShowForm(false)}><form className="catalog-modal expense-balance-form" onSubmit={saveAccount}>
      <div className="catalog-modal-heading"><div><span className="catalog-eyebrow">BALANCE SHEET</span><h2>{editing.name}</h2><p>Enter this account’s current balance.</p></div><button className="catalog-icon-button" type="button" onClick={() => setShowForm(false)} aria-label="Close"><X size={18}/></button></div>
      <label className="catalog-field">{sheet?.current_year} {editing.editable_current && editing.source !== 'Manual balance' ? 'additional balance' : 'balance'}<input required type="number" step="0.01" value={currentAmount} onChange={(event) => setCurrentAmount(event.target.value)} disabled={!editing.editable_current}/></label>
      {!editing.editable_current && <p className="expense-balance-source-note">This value is calculated from live business records.</p>}
      {editing.editable_current && editing.source !== 'Manual balance' && <p className="expense-balance-source-note">Approved unpaid expenses are included automatically. Add other current liabilities here.</p>}
      {error && <p className="catalog-form-error">{error}</p>}
      <div className="catalog-modal-actions"><button type="button" className="catalog-button catalog-button-light" onClick={() => setShowForm(false)}>Cancel</button><button className="catalog-button catalog-button-primary" disabled={saving}>{saving ? 'Saving…' : 'Save balance'}</button></div>
    </form></div>}
  </section>;
}

export default function ExpensesDashboard({ onOpenReports }: { onOpenReports: () => void }) {
  const [summary, setSummary] = useState<ExpenseSummary | null>(null);
  const [expenseOptions, setExpenseOptions] = useState<ExpenseOptions>({ categories: [], types: [] });
  const [expenseOptionsLoading, setExpenseOptionsLoading] = useState(true);
  const [expenseOptionsError, setExpenseOptionsError] = useState('');
  const [month, setMonth] = useState(localDate().slice(0, 7));
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [paymentFilter, setPaymentFilter] = useState('all');
  const [receiptFilter, setReceiptFilter] = useState<ReceiptFilter>('all');
  const [search, setSearch] = useState('');
  const [trend, setTrend] = useState<ExpenseTrend>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showExpenseForm, setShowExpenseForm] = useState(false);
  const [budgetTarget, setBudgetTarget] = useState<ExpenseBudget | null | undefined>(undefined);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [notice, setNotice] = useState('');
  const [showBalanceSheet, setShowBalanceSheet] = useState(false);
  const [showExpenseOptions, setShowExpenseOptions] = useState(false);

  async function loadSummary() {
    setLoading(true);
    setError('');
    try { setSummary(await api.expenseSummary(month)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'The expense service could not be reached.'); }
    finally { setLoading(false); }
  }

  async function loadExpenseOptions() {
    setExpenseOptionsLoading(true);
    setExpenseOptionsError('');
    try { setExpenseOptions(await api.expenseOptions()); }
    catch (cause) { setExpenseOptionsError(cause instanceof Error ? cause.message : 'Expense categories and types could not be loaded.'); }
    finally { setExpenseOptionsLoading(false); }
  }

  useEffect(() => { void loadSummary(); }, [month]);
  useEffect(() => { void loadExpenseOptions(); }, []);

  const expenses = useMemo(() => (summary?.expenses ?? []).filter((expense) => {
    const term = search.trim().toLowerCase();
    const matchesSearch = !term || `${expense.expense_number} ${expense.merchant} ${expense.description} ${expense.reference} ${expense.cost_center}`.toLowerCase().includes(term);
    const matchesCategory = categoryFilter === 'all' || expense.category === categoryFilter;
    const matchesPayment = paymentFilter === 'all' || expense.payment_method === paymentFilter;
    const matchesReceipt = receiptFilter === 'all' || (receiptFilter === 'verified' ? expense.receipt_verified : !expense.receipt_received);
    return matchesSearch && matchesCategory && matchesPayment && matchesReceipt;
  }), [summary, search, categoryFilter, paymentFilter, receiptFilter]);
  const chartData = summary?.daily_series ?? [];
  const selectedSeries = chartData.map((day) => trend === 'all' ? day.total : day.types[trend] ?? 0);
  const maximumSpend = Math.max(...selectedSeries, 1);

  async function updateStatus(expense: Expense, status: Expense['status']) {
    setBusyId(expense.id);
    try {
      await api.updateExpense(expense.id, { status });
      await loadSummary();
      setNotice(`${expense.expense_number} updated to ${status}.`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not update expense status.'); }
    finally { setBusyId(null); }
  }

  async function saveBudget(input: Pick<ExpenseBudget, 'category' | 'monthly_limit' | 'cost_center' | 'manager'>) {
    if (budgetTarget) await api.updateExpenseBudget(budgetTarget.id, input);
    else await api.createExpenseBudget(input);
    setBudgetTarget(undefined);
    await loadSummary();
    setNotice('Budget guardrail saved.');
  }

  async function addExpenseOption(kind: 'category' | 'type', name: string) {
    const updatedOptions = await api.createExpenseOption(kind, name);
    setExpenseOptions(updatedOptions);
    await loadSummary();
    setNotice(`Expense ${kind} added.`);
  }

  async function deleteExpenseCategory(category: ExpenseCategoryOption) {
    const updatedOptions = await api.deleteExpenseCategory(category.id);
    setExpenseOptions(updatedOptions);
    if (categoryFilter === category.name) setCategoryFilter('all');
    setNotice(`${category.name} removed from future expense options. Existing expenses and budgets were kept.`);
  }

  async function deleteExpenseType(type: ExpenseTypeOption) {
    const updatedOptions = await api.deleteExpenseType(type.id);
    setExpenseOptions(updatedOptions);
    if (trend === type.value) setTrend('all');
    setNotice(`${type.label} removed from future expense options. Existing expense records were kept.`);
  }

  function expenseExportRows(): unknown[][] {
    return [
      ['merchant', 'description', 'category', 'cost_center', 'expense_type', 'amount_before_tax', 'tax_amount', 'payment_method', 'status', 'reference', 'expense_date', 'receipt_received', 'receipt_verified', 'entered_by'],
      ...expenses.map((expense) => [expense.merchant, expense.description, expense.category, expense.cost_center, expense.expense_type, expense.amount_before_tax, expense.tax_amount, expense.payment_method, expense.status, expense.reference, expense.expense_date, expense.receipt_received, expense.receipt_verified, expense.entered_by]),
    ];
  }
  function exportCsv() {
    const rows = expenseExportRows();
    const csv = rows.map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `stockpulse-expenses-${month}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }
  async function exportXlsx() {
    try { await downloadSpreadsheet(`stockpulse-expenses-${month}.xlsx`, 'Expenses', expenseExportRows()); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Excel export failed.'); }
  }

  async function uploadExpenses(file?: File) {
    if (!file) return;
    setError('');
    try {
      const [header, ...lines] = await readSpreadsheetRows(file);
      if (!header || !lines.length) throw new Error('The file does not contain any expense rows.');
      const indexes = new Map(header.map((value, index) => [value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, ''), index]));
      const value = (row: string[], key: string) => row[indexes.get(key) ?? -1]?.trim() ?? '';
      const imported: ExpenseInput[] = lines.map((row) => ({
        merchant: value(row, 'merchant'), description: value(row, 'description'), category: value(row, 'category'),
        cost_center: value(row, 'cost_center'), expense_type: (value(row, 'expense_type') || 'operational') as ExpenseInput['expense_type'],
        amount_before_tax: value(row, 'amount_before_tax'), tax_amount: value(row, 'tax_amount') || '0.00',
        payment_method: (value(row, 'payment_method') || 'bank') as ExpenseInput['payment_method'],
        status: (value(row, 'status') || 'pending') as ExpenseInput['status'], reference: value(row, 'reference'),
        expense_date: value(row, 'expense_date') || `${month}-01`, receipt_received: value(row, 'receipt_received').toLowerCase() === 'true',
        receipt_verified: value(row, 'receipt_verified').toLowerCase() === 'true', entered_by: value(row, 'entered_by'),
      }));
      await api.bulkCreateExpenses(imported);
      await loadSummary();
      setNotice(`${imported.length} expense records imported.`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Expense upload failed. Check the file columns and values.'); }
    finally { if (fileInputRef.current) fileInputRef.current.value = ''; }
  }

  function chooseExpenseImport(accept: string) {
    if (!fileInputRef.current) return;
    fileInputRef.current.accept = accept;
    fileInputRef.current.click();
  }

  const fileInputRef = useRef<HTMLInputElement>(null);

  return <>
    <section className="catalog-heading expenses-heading"><div><div className="catalog-breadcrumb">Finance &amp; Accounting <span>›</span> <b>Expenses Ledger</b></div><h1>Expenses &amp; Disbursements</h1><p>Track operating expenses, vendor overhead, and receipt audit trails across business units.</p></div><div className="catalog-heading-actions"><FileActionMenu label="Import" direction="import" options={[{ label: 'CSV file', onSelect: () => chooseExpenseImport('.csv,text/csv') }, { label: 'Excel workbook', onSelect: () => chooseExpenseImport('.xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel') }]}/><input ref={fileInputRef} className="catalog-hidden" type="file" onChange={(event) => void uploadExpenses(event.target.files?.[0])}/><FileActionMenu label="Export" direction="export" options={[{ label: 'CSV file', onSelect: exportCsv, disabled: !expenses.length }, { label: 'Excel workbook', onSelect: () => void exportXlsx(), disabled: !expenses.length }]}/><button className="catalog-button catalog-button-light" type="button" disabled={expenseOptionsLoading || Boolean(expenseOptionsError)} onClick={() => setShowExpenseOptions(true)}><Settings2 size={14}/>Expense settings</button><button className={`catalog-button ${showBalanceSheet ? 'catalog-button-primary' : 'catalog-button-light'}`} type="button" aria-expanded={showBalanceSheet} onClick={() => setShowBalanceSheet((visible) => !visible)}><Landmark size={14}/>{showBalanceSheet ? 'Hide balance sheet' : 'Balance sheet'}</button><button className="catalog-button catalog-button-primary" disabled={expenseOptionsLoading || Boolean(expenseOptionsError)} onClick={() => setShowExpenseForm(true)}><Plus size={14}/>Record expense</button></div></section>
    <div className="expenses-period-row"><span>Month-to-date ledger</span><label className="catalog-select"><input aria-label="Expense month" type="month" value={month} onChange={(event) => setMonth(event.target.value)}/><ChevronDown size={12}/></label><button className="overview-text-action" onClick={onOpenReports}>Financial reports →</button></div>
    {expenseOptionsError && <div className="expense-inline-error"><CircleAlert size={13}/>{expenseOptionsError}<button type="button" className="overview-text-action" onClick={() => void loadExpenseOptions()}>Retry</button></div>}
    {showBalanceSheet && <BalanceSheetPanel/>}
    {loading && <section className="overview-state">Loading expense ledger…</section>}
    {!loading && error && !summary && <section className="overview-state overview-error"><strong>Could not load expenses</strong><span>{error}</span><button className="catalog-button catalog-button-light" onClick={() => void loadSummary()}><RefreshCw size={14}/>Retry</button></section>}
    {!loading && summary && <>
      <section className="expenses-metrics"><article><div><span>TOTAL MTD EXPENSES</span><ReceiptText size={14}/></div><strong>{currency(summary.total_expenses)}</strong><small><ArrowUpRight size={11}/> {summary.expense_count} expense records</small></article><article className="pending"><div><span>PENDING APPROVAL</span><CircleAlert size={14}/></div><strong>{currency(summary.pending_approval)}</strong><small>{summary.pending_count} vouchers awaiting sign-off</small></article><article><div><span>LARGEST CATEGORY</span><Wallet size={14}/></div><strong className="expense-largest-category">{summary.largest_category?.name ?? '—'}</strong><small>{summary.largest_category ? `${currency(summary.largest_category.total)} recorded · ${summary.largest_category.percent}% of spend` : 'No expenses recorded'}</small></article><article className="tax-reclaimable"><div><span>TAX RECLAIMABLE</span><ShieldCheck size={14}/></div><strong>{currency(summary.tax_reclaimable)}</strong><small>{summary.verified_receipts} verified receipts</small></article></section>
      <div className="expenses-insight-grid"><section className="overview-panel expense-trend-panel"><div className="overview-panel-heading"><div><span>MONTHLY EXPENSE VELOCITY</span><h2>Spend distribution</h2></div><div className="expense-trend-tabs" role="tablist" aria-label="Expense type"><button className={trend === 'all' ? 'active' : ''} onClick={() => setTrend('all')}>All</button>{expenseOptions.types.map((item) => <button key={item.value} className={trend === item.value ? 'active' : ''} onClick={() => setTrend(item.value)}>{item.label}</button>)}</div></div><div className="expense-trend-chart" role="img" aria-label={`${trend} daily expense trend`}>{chartData.map((day, index) => <div key={day.label} title={`${day.label}: ${currency(selectedSeries[index])}`}><i style={{ height: `${selectedSeries[index] ? Math.max(selectedSeries[index] / maximumSpend * 100, 2) : 0}%` }}/></div>)}</div><div className="expense-trend-labels"><span>{summary.start_date}</span><span>{summary.end_date}</span></div><div className="expense-category-heading"><div><span>OVERALL ALLOCATION</span><strong>{currency(summary.total_expenses)} MTD</strong></div><button className="overview-text-action" onClick={onOpenReports}>{summary.categories.length} categories active</button></div><div className="expense-allocation-bar">{summary.categories.slice(0, 6).map((category, index) => <i key={category.name} title={`${category.name}: ${currency(category.total)}`} style={{ width: `${category.percent}%`, background: ['#2865e9', '#7f9bea', '#aab8d8', '#c8d1e3', '#43bd8b', '#e6a23c'][index % 6] }}/>)}</div><div className="expense-category-legend">{summary.categories.slice(0, 5).map((category, index) => <span key={category.name}><i style={{ background: ['#2865e9', '#7f9bea', '#aab8d8', '#c8d1e3', '#43bd8b'][index % 5] }}/>{category.name} <strong>{currency(category.total)}</strong></span>)}</div></section>
        <section className="overview-panel expense-budget-panel"><div className="overview-panel-heading"><div><span>BUDGET GUARDRAILS</span><h2>Monthly caps vs. actual spend</h2></div><button className="catalog-clear" onClick={() => setBudgetTarget(null)}><Plus size={12}/>Add budget</button></div>{summary.budgets.map((budget) => <div className="expense-budget-row" key={budget.id}><div><strong>{budget.category}</strong><span>{currency(budget.spent)} / {currency(budget.monthly_limit)}</span><b className={budget.percent_used > 100 ? 'over-budget' : ''}>{budget.percent_used}%</b></div><div className="expense-budget-track"><i className={budget.percent_used > 100 ? 'over-budget' : ''} style={{ width: `${Math.min(budget.percent_used, 100)}%` }}/></div></div>)}{!summary.budgets.length && <div className="expense-budget-empty"><p>No category budgets configured.</p><button className="catalog-button catalog-button-light" onClick={() => setBudgetTarget(null)}><Plus size={13}/>Set a budget</button></div>}<div className="expense-budget-note"><ShieldCheck size={13}/><span>Budget status updates as expenses are recorded.</span></div></section></div>
      {error && <div className="expense-inline-error"><CircleAlert size={13}/>{error}</div>}
      {notice && <div className="catalog-toast"><Check size={15}/>{notice}<button onClick={() => setNotice('')} aria-label="Dismiss"><X size={14}/></button></div>}
      <section className="catalog-filter-panel expense-filters"><div className="catalog-filter-row"><label className="catalog-search product-search"><Search size={14}/><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search voucher, merchant, description"/></label><label className="catalog-select"><select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}><option value="all">All categories</option>{expenseOptions.categories.map((category) => <option key={category.id} value={category.name}>{category.name}</option>)}</select><ChevronDown size={12}/></label><label className="catalog-select"><select value={paymentFilter} onChange={(event) => setPaymentFilter(event.target.value)}><option value="all">All payment methods</option><option value="card">Card</option><option value="bank">ACH / wire</option><option value="cash">Cash</option><option value="check">Check</option><option value="petty_cash">Petty cash</option></select><ChevronDown size={12}/></label><label className="catalog-select"><select value={receiptFilter} onChange={(event) => setReceiptFilter(event.target.value as ReceiptFilter)}><option value="all">All receipts</option><option value="verified">Verified</option><option value="missing">Missing</option></select><ChevronDown size={12}/></label><span className="expense-date-range">{summary.start_date} – {summary.end_date}</span></div></section>
      <section className="catalog-table-panel expense-table-panel"><div className="catalog-table-scroll"><table className="catalog-table expense-table"><thead><tr><th>EXPENSE / VOUCHER #</th><th>MERCHANT &amp; DESCRIPTION</th><th>COST CENTER</th><th>AMOUNT &amp; TAX</th><th>PAYMENT</th><th>STATUS</th><th>RECEIPT</th><th>ACTION</th></tr></thead><tbody>{expenses.map((expense) => <tr key={expense.id}><td><strong className="expense-number">{expense.expense_number}</strong><small>{new Date(`${expense.expense_date}T00:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</small></td><td><strong className="expense-merchant">{expense.merchant}</strong><small>{expense.description}</small></td><td><span className="expense-cost-center">{expense.cost_center || expense.category}</span></td><td><strong>{currency(expense.total_amount)}</strong><small>{expense.tax_amount === '0.00' ? 'Tax exempt' : `Incl. ${currency(expense.tax_amount)} tax`}</small></td><td>{expense.payment_method_display}</td><td><span className={`expense-status ${expense.status}`}>{expense.status_display}</span></td><td><span className={`expense-receipt-status ${expense.receipt_verified ? 'verified' : expense.receipt_received ? 'received' : 'missing'}`}>{expense.receipt_verified ? 'Verified' : expense.receipt_received ? 'Received' : 'Missing'}</span></td><td><select className="expense-status-select" aria-label={`Update ${expense.expense_number} status`} disabled={busyId === expense.id} value={expense.status} onChange={(event) => void updateStatus(expense, event.target.value as Expense['status'])}><option value="pending">Pending</option><option value="approved">Approved</option><option value="paid">Paid</option><option value="rejected">Rejected</option></select></td></tr>)}{!expenses.length && <tr><td colSpan={8} className="catalog-state">No expenses match these filters.</td></tr>}</tbody></table></div><footer className="catalog-table-footer"><span>Showing <b>{expenses.length}</b> of <b>{summary.expense_count}</b> records</span><button className="catalog-clear" onClick={() => { setSearch(''); setCategoryFilter('all'); setPaymentFilter('all'); setReceiptFilter('all'); }}>Clear filters</button></footer></section>
    </>}
    {showExpenseForm && <ExpenseForm categories={expenseOptions.categories} types={expenseOptions.types} onClose={() => setShowExpenseForm(false)} onSaved={async () => { setShowExpenseForm(false); await loadSummary(); setNotice('Expense recorded in the ledger.'); }}/>}
    {showExpenseOptions && <ExpenseOptionsForm categories={expenseOptions.categories} types={expenseOptions.types} onClose={() => setShowExpenseOptions(false)} onAdd={addExpenseOption} onDeleteCategory={deleteExpenseCategory} onDeleteType={deleteExpenseType}/>}
    {budgetTarget !== undefined && <BudgetForm initial={budgetTarget} onClose={() => setBudgetTarget(undefined)} onSaved={saveBudget}/>}
  </>;
}
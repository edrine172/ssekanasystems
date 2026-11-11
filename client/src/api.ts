import { requestMutationConfirmation } from './ConfirmDialog';
import { notifyDataChanged } from './dataSync';

const configuredApiBase = import.meta.env.VITE_API_BASE_URL?.trim();
const normalizedApiBase = configuredApiBase?.replace(/\/+$/, '');
const API_BASE = normalizedApiBase
  ? (normalizedApiBase.endsWith('/api') ? normalizedApiBase : `${normalizedApiBase}/api`)
  : (import.meta.env.DEV ? 'http://localhost:8000/api' : '');
let accessCsrfToken = '';

export class AdministratorSessionExpiredError extends Error {
  constructor() {
    super('Your administrator session has expired. Sign in again to continue.');
    this.name = 'AdministratorSessionExpiredError';
  }
}

const administratorSessionExpiredListeners = new Set<() => void>();

export function subscribeToAdministratorSessionExpired(listener: () => void) {
  administratorSessionExpiredListeners.add(listener);
  return () => {
    administratorSessionExpiredListeners.delete(listener);
  };
}

function isAdministratorSessionExpired(status: number, body: string) {
  if (status === 401) return true;
  if (status !== 403 || !body) return false;
  try {
    const payload = JSON.parse(body) as { detail?: unknown };
    return payload.detail === 'Authentication credentials were not provided.'
      || payload.detail === 'Administrator sign-in required.';
  } catch (cause) {
    if (cause instanceof SyntaxError) return false;
    throw cause;
  }
}

async function throwIfAdministratorSessionExpired(response: Response) {
  if (response.status !== 401 && response.status !== 403) return;
  const body = await response.clone().text();
  if (!isAdministratorSessionExpired(response.status, body)) return;
  administratorSessionExpiredListeners.forEach((listener) => listener());
  throw new AdministratorSessionExpiredError();
}

async function fetchWithNetworkRetries(url: string, options?: RequestInit) {
  for (let attempt = 0; attempt < 7; attempt += 1) {
    try {
      return await fetch(url, options);
    } catch (cause) {
      if (!(cause instanceof TypeError)) throw cause;
      if (attempt === 6) {
        throw new Error('Could not reach the server. Check your connection and try again.');
      }
      await new Promise((resolve) => setTimeout(resolve, Math.min(1000 * (2 ** attempt), 12000)));
    }
  }
  throw new Error('Could not reach the server. Check your connection and try again.');
}

async function fetchGet(url: string, options?: RequestInit) {
  return fetchWithNetworkRetries(url, { ...options, method: 'GET', cache: 'no-store' });
}

function apiUrl(path: string) {
  if (!API_BASE) {
    throw new Error('Backend URL is not configured. Set VITE_API_BASE_URL in Vercel to your Render service URL ending in /api, then redeploy.');
  }
  return `${API_BASE}${path}`;
}

function csrfInitializationError(response: Response) {
  return new Error(`Could not initialize secure account access (HTTP ${response.status}). Check that VITE_API_BASE_URL points to your live Render API and ends in /api.`);
}

export interface ExchangeRatesData {
  base_currency: 'UGX';
  currency: string;
  rates: Record<string, number>;
  updated_at: string;
}

interface CurrencyDisplay {
  currency: string;
  rates: Record<string, number>;
  updatedAt: string | null;
}

const currencyDisplayListeners = new Set<() => void>();
let currencyDisplay: CurrencyDisplay = { currency: 'UGX', rates: { UGX: 1 }, updatedAt: null };

export function getCurrencyDisplay(): CurrencyDisplay {
  return currencyDisplay;
}

export function subscribeCurrencyDisplay(listener: () => void) {
  currencyDisplayListeners.add(listener);
  return () => currencyDisplayListeners.delete(listener);
}

export function setCurrencyDisplay(currency: string, rates: Record<string, number>, updatedAt: string | null) {
  currencyDisplay = { currency, rates: { ...rates, UGX: 1 }, updatedAt };
  currencyDisplayListeners.forEach((listener) => listener());
}

export interface AccessUser {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  display_name?: string;
  is_active: boolean;
  is_staff: boolean;
  is_superuser: boolean;
  last_login: string | null;
  date_joined: string;
  groups: Array<number | { id: number; name: string }>;
  group_names?: string[];
}

export interface AccessGroup {
  id: number;
  name: string;
  permission_ids: number[];
  permission_labels: string[];
  member_count: number;
}

export interface AccessPermission {
  id: number;
  codename: string;
  model: string;
  label: string;
  action: string;
}

export interface SecurityAuditEvent {
  id: number;
  actor_name: string;
  action: string;
  target_type: string;
  target_id: string;
  details: Record<string, unknown>;
  created_at: string;
}

export type NotificationDashboard = 'overview' | 'products' | 'inventory' | 'purchases' | 'po-client' | 'pos' | 'sales' | 'reports' | 'customers' | 'suppliers' | 'expenses' | 'account' | 'users' | 'settings' | 'staff';
export type NotificationCategory = 'stock' | 'procurement' | 'billing' | 'operations';

export interface AppNotification {
  id: number;
  category: NotificationCategory;
  severity: 'info' | 'warning' | 'critical';
  title: string;
  message: string;
  target_label: string;
  dashboard: NotificationDashboard;
  is_read: boolean;
  created_at: string;
}

export interface AccessDashboardData {
  active_users: number;
  total_users: number;
  role_count: number;
  disabled_users: number;
  staff_users: number;
  permission_count: number;
  users: AccessUser[];
  groups: AccessGroup[];
  permissions: AccessPermission[];
  audit_log: SecurityAuditEvent[];
}

export interface SystemSettings {
  organization: {
    business_name: string;
    tax_id: string;
    currency: string;
    timezone: string;
    default_warehouse: string;
  };
  operations: {
    reorder_threshold: number;
    allow_negative_stock: boolean;
    auto_purchase_drafts: boolean;
    default_payment_terms: string;
  };
  security: {
    require_two_factor: boolean;
    session_timeout_minutes: number;
    audit_retention_days: number;
  };
  integrations: {
    quickbooks_enabled: boolean;
    stripe_enabled: boolean;
    webhooks_enabled: boolean;
  };
}

export interface SettingsAuditEvent {
  id: number;
  actor_name: string;
  action: string;
  target_id: string;
  details: { previous: unknown; value: unknown };
  created_at: string;
}

export interface SystemSettingsData {
  settings: SystemSettings;
  audit_log: SettingsAuditEvent[];
}

export const formatCurrency = (value: number | string) => {
  const rate = currencyDisplay.rates[currencyDisplay.currency];
  const currency = rate && Number.isFinite(rate) ? currencyDisplay.currency : 'UGX';
  return new Intl.NumberFormat('en-UG', {
    style: 'currency', currency, maximumFractionDigits: 2,
  }).format((Number(value) || 0) * (currency === 'UGX' ? 1 : rate));
};

export interface Product {
  id: number;
  sku: string;
  name: string;
  category: number;
  category_name: string;
  supplier: number | null;
  supplier_name: string;
  quantity: number;
  reorder_level: number;
  is_active: boolean;
  unit_price: string;
  cost_price: string;
  location: string;
  updated_at: string;
}

export interface DashboardSummary {
  total_skus: number;
  total_units: number;
  inventory_value: string;
  low_stock_count: number;
  out_of_stock_count: number;
  today_sales: string;
  today_purchases: string;
  gross_profit: string;
  gross_margin: number;
  period_sales: string;
  period_purchases: string;
  products: Product[];
  recent_movements: StockMovement[];
  categories: Array<{ id: number; name: string; units: number; value: string; percent: number }>;
  series: Array<{ label: string; sales: number; purchases: number }>;
}

export interface StockMovement {
  id: number;
  product: number;
  product_name: string;
  product_sku: string;
  supplier_name: string;
  movement_type: 'inbound' | 'outbound' | 'adjustment' | 'return';
  quantity: number;
  amount: string;
  note: string;
  reference: string;
  created_at: string;
}

export interface Category { id: number; name: string; description: string }
export interface Supplier {
  id: number;
  supplier_code: string;
  name: string;
  contact_name: string;
  email: string;
  phone: string;
  sector: string;
  account_manager: string;
  address: string;
  tax_number: string;
  contract_number: string;
  payment_terms: string;
  outstanding_balance: string;
  is_active: boolean;
  lead_time_days: number;
  lifetime_spend: string;
  completed_orders: number;
  on_time_delivery_rate: number | null;
  created_at: string;
}

export interface SupplierLedgerEntry {
  id: number;
  entry_type: 'charge' | 'payment' | 'credit';
  entry_type_display: string;
  amount: string;
  payment_method: 'cash' | 'card' | 'mobile' | 'transfer' | 'check' | '';
  payment_method_display: string;
  reference: string;
  note: string;
  purchase_reference: string;
  created_at: string;
}

export interface SupplierDashboardData {
  supplier: Supplier;
  lifetime_spend: string;
  outstanding_balance: string;
  open_order_value: string;
  received_orders: number;
  purchase_orders: Purchase[];
  ledger_entries: SupplierLedgerEntry[];
  supplied_products: Product[];
}

export interface Customer {
  id: number;
  customer_code: string;
  name: string;
  contact_name: string;
  email: string;
  phone: string;
  sector: string;
  tier: 'standard' | 'growth' | 'enterprise';
  account_manager: string;
  billing_address: string;
  shipping_address: string;
  tax_number: string;
  tax_exempt: boolean;
  payment_terms: string;
  credit_limit: string;
  outstanding_balance: string;
  is_active: boolean;
  lifetime_revenue: string;
  completed_orders: number;
  created_at: string;
}

export interface CustomerLedgerEntry {
  id: number;
  entry_type: 'charge' | 'payment' | 'credit';
  entry_type_display: string;
  amount: string;
  payment_method: 'cash' | 'card' | 'mobile' | 'transfer' | 'check' | '';
  payment_method_display: string;
  reference: string;
  note: string;
  sale_reference: string;
  created_at: string;
}

export interface CustomerDashboardData {
  customer: Customer;
  lifetime_revenue: string;
  completed_orders: number;
  outstanding_balance: string;
  total_paid_amount: string;
  total_remaining_balance: string;
  account_charges: string;
  account_payments: string;
  account_credits: string;
  sales: Sale[];
  bottle_purchase_orders: BottleCustomerPO[];
  client_material_purchase_orders: ClientMaterialPO[];
  ledger_entries: CustomerLedgerEntry[];
}

export interface InventoryAdjustment {
  product: number;
  adjustment_type: 'increase' | 'decrease' | 'damage' | 'loss' | 'count';
  quantity?: number;
  counted_quantity?: number;
  reason: string;
  reference?: string;
  notes?: string;
}

export interface PurchaseItem {
  id: number;
  product: number;
  product_name: string;
  product_sku: string;
  quantity: number;
  unit_cost: string;
  line_total: string;
}

export interface Purchase {
  id: number;
  reference: string;
  supplier: number;
  supplier_name: string;
  status: 'ordered' | 'received' | 'cancelled';
  items: PurchaseItem[];
  item_count: number;
  total: string;
  paid_amount: string;
  remaining_balance: string;
  payment_status: 'not_due' | 'unpaid' | 'partial' | 'paid';
  payments: SupplierLedgerEntry[];
  notes: string;
  expected_delivery: string | null;
  ordered_at: string;
  received_at: string | null;
}

export interface PurchaseSummary {
  total_orders: number;
  open_orders: number;
  received_this_month: number;
  open_value: string;
  spent_this_month: string;
  recent_purchases: Purchase[];
}

export interface BottleProduct {
  id: number;
  sku: string;
  name: string;
  category: string;
  unit: string;
  quantity: number;
  unit_price: string;
  is_active: boolean;
  created_at: string;
}

export interface BottleCustomerPOLine {
  id: number;
  product: number;
  product_name: string;
  product_sku: string;
  category: string;
  unit: string;
  quantity: number;
  unit_price: string;
  line_total: string;
  delivered_quantity: number;
  remaining_quantity: number;
}

export interface BottleCustomerPO {
  id: number;
  reference: string;
  customer: number;
  customer_name: string;
  items: BottleCustomerPOLine[];
  deliveries: BottleCustomerDelivery[];
  total: string;
  status: 'open' | 'partial' | 'completed';
  expected_delivery: string | null;
  notes: string;
  ordered_at: string;
}

export interface BottleCustomerDelivery {
  id: number;
  reference: string;
  notes: string;
  delivered_at: string;
  items: Array<{ id: number; purchase_order_line: number; product_name: string; product_sku: string; unit: string; quantity: number }>;
}

export interface ClientMaterial {
  id: number;
  material_type: string;
  name: string;
  quantity: string;
  unit: string;
  unit_price: string;
}

export interface ClientMaterialReceipt {
  id: number;
  reference: string;
  quantity: string;
  notes: string;
  received_at: string;
}

export interface ClientMaterialPO {
  id: number;
  reference: string;
  customer: number;
  customer_name: string;
  material: number;
  material_name: string;
  material_unit: string;
  quantity: string;
  unit_price: string;
  total: string;
  received_quantity: string;
  remaining_quantity: string;
  status: 'open' | 'partial' | 'completed';
  expected_delivery: string | null;
  notes: string;
  ordered_at: string;
  receipts: ClientMaterialReceipt[];
}

export interface SaleLine {
  id: number;
  product: number;
  product_name: string;
  product_sku: string;
  quantity: number;
  unit_price: string;
  unit_cost: string;
  line_total: string;
}

export interface Sale {
  id: number;
  receipt_number: string;
  customer: number | null;
  customer_name: string;
  payment_method: 'cash' | 'card' | 'mobile' | 'transfer' | 'account';
  payment_method_display: string;
  subtotal: string;
  discount_percent: string;
  discount_amount: string;
  tax_rate: string;
  tax_amount: string;
  total: string;
  cash_tendered: string | null;
  change_due: string;
  paid_amount: string;
  remaining_balance: string;
  payment_status: 'paid' | 'partial' | 'unpaid';
  items: SaleLine[];
  payments: CustomerLedgerEntry[];
  created_at: string;
}

export interface SalesSummary {
  today_sales: string;
  transactions_today: number;
  recent_sales: Sale[];
}

export interface ReportsSummary {
  range_days: number;
  series_interval: 'day' | 'month' | 'year';
  start_date: string;
  end_date: string;
  revenue: string;
  previous_revenue: string;
  revenue_change_percent: number;
  cost_of_goods: string;
  gross_profit: string;
  gross_margin: number;
  operating_expenses: string;
  net_profit: string;
  inventory_value: string;
  inventory_units: number;
  total_skus: number;
  low_stock_count: number;
  out_of_stock_count: number;
  inventory_turnover: number;
  purchase_spend: string;
  received_orders: number;
  open_orders: number;
  open_purchase_value: string;
  daily_series: Array<{ label: string; revenue: number; cost_of_goods: number; gross_profit: number; purchases: number; expenses: number; net_profit: number }>;
  categories: Array<{ name: string; units: number; revenue: string; percent: number }>;
  inventory_categories: Array<{ name: string; units: number; revenue: string; percent: number }>;
  purchase_categories: Array<{ name: string; units: number; revenue: string; percent: number }>;
  top_products: Array<{
    product_name: string;
    product_sku: string;
    category_name: string;
    units_sold: number;
    revenue: string;
    cost: string;
    gross_profit: string;
    gross_margin: number;
    average_price: string;
  }>;
}

export interface Expense {
  id: number;
  expense_number: string;
  merchant: string;
  description: string;
  category: string;
  cost_center: string;
  expense_type: string;
  amount_before_tax: string;
  tax_amount: string;
  total_amount: string;
  payment_method: 'card' | 'bank' | 'cash' | 'check' | 'petty_cash';
  payment_method_display: string;
  status: 'pending' | 'approved' | 'paid' | 'rejected';
  status_display: string;
  reference: string;
  expense_date: string;
  receipt_received: boolean;
  receipt_verified: boolean;
  entered_by: string;
  created_at: string;
  updated_at: string;
}

export type ExpenseInput = Pick<Expense, 'merchant' | 'description' | 'category' | 'cost_center' | 'expense_type' | 'amount_before_tax' | 'tax_amount' | 'payment_method' | 'status' | 'reference' | 'expense_date' | 'receipt_received' | 'receipt_verified' | 'entered_by'>;

export interface ExpenseBudget {
  id: number;
  category: string;
  monthly_limit: string;
  cost_center: string;
  manager: string;
  spent: string;
  percent_used: number;
  updated_at?: string;
}

export interface ExpenseSummary {
  month: string;
  start_date: string;
  end_date: string;
  total_expenses: string;
  pending_approval: string;
  pending_count: number;
  tax_reclaimable: string;
  verified_receipts: number;
  expense_count: number;
  largest_category: { name: string; total: string; percent: number } | null;
  categories: Array<{ name: string; total: string; count: number; percent: number }>;
  budgets: ExpenseBudget[];
  daily_series: Array<{ label: string; total: number; types: Record<string, number> }>;
  expense_types: ExpenseTypeOption[];
  expenses: Expense[];
  can_edit_expenses: boolean;
}

export interface ExpenseCategoryOption {
  id: number;
  name: string;
}

export interface ExpenseTypeOption {
  id: number;
  value: string;
  label: string;
}

export interface ExpenseOptions {
  categories: ExpenseCategoryOption[];
  types: ExpenseTypeOption[];
}

export type BalanceSheetCategory =
  | 'cash_and_cash_equivalents'
  | 'current_marketable_securities'
  | 'accounts_receivable_net'
  | 'inventories'
  | 'vendor_non_trade_receivables'
  | 'other_current_assets'
  | 'noncurrent_marketable_securities'
  | 'property_plant_equipment_net'
  | 'other_noncurrent_assets'
  | 'accounts_payable'
  | 'other_current_liabilities'
  | 'deferred_revenue'
  | 'commercial_paper'
  | 'current_term_debt'
  | 'noncurrent_term_debt'
  | 'other_noncurrent_liabilities'
  | 'common_stock_and_additional_paid_in_capital'
  | 'retained_earnings'
  | 'accumulated_other_comprehensive_income_loss';

export interface BalanceSheetAccount {
  id: number;
  category: BalanceSheetCategory;
  amount: string | null;
  prior_amount: string | null;
  updated_at: string;
}

export interface BalanceSheetLine {
  category: BalanceSheetCategory;
  name: string;
  current_amount: string | null;
  manual_current_amount: string | null;
  prior_amount: string | null;
  source: string;
  updated_at: string | null;
  editable_current: boolean;
  current_complete: boolean;
  prior_complete: boolean;
}

export interface BalanceSheetGroup {
  title: string;
  current_total: string;
  prior_total: string;
  current_complete: boolean;
  prior_complete: boolean;
  rows: BalanceSheetLine[];
}

export interface BalanceSheetSection {
  current_total: string;
  prior_total: string;
  current_complete: boolean;
  prior_complete: boolean;
  groups: BalanceSheetGroup[];
}

export interface BalanceSheetSummary {
  as_of_date: string;
  current_year: number;
  prior_year: number;
  assets: BalanceSheetSection;
  liabilities: BalanceSheetSection;
  equity: BalanceSheetSection;
  total_assets: string;
  total_liabilities: string;
  total_equity: string;
  difference: string;
  is_balanced: boolean;
  current_complete: boolean;
  prior_difference: string;
  is_prior_balanced: boolean;
  prior_complete: boolean;
}

export interface StaffMember {
  id: number;
  employee_number: string;
  full_name: string;
  email: string;
  phone: string;
  job_title: string;
  department: string;
  pay_basis: 'monthly' | 'hourly' | 'daily';
  pay_basis_display: string;
  pay_rate: string;
  hours_per_period: string;
  period_days_worked: number;
  period_gross: string;
  period_task_pay: string;
  withholding_percent: string;
  benefit_deduction: string;
  status: 'active' | 'leave' | 'inactive';
  status_display: string;
  hire_date: string;
  created_at: string;
  updated_at: string;
}

export interface PayrollLine {
  id: number;
  worker: number;
  employee_number: string;
  worker_name: string;
  job_title: string;
  department: string;
  pay_basis: 'monthly' | 'hourly' | 'daily';
  hours: string;
  days_worked: number;
  task_pay: string;
  gross_pay: string;
  withholding: string;
  benefits: string;
  net_pay: string;
}

export interface PayrollRun {
  id: number;
  period: string;
  status: 'scheduled' | 'paid';
  status_display: string;
  worker_count: number;
  gross_total: string;
  withholding_total: string;
  benefits_total: string;
  net_total: string;
  created_at: string;
  paid_at: string | null;
  lines: PayrollLine[];
}

export interface StaffAttendance {
  id: number;
  worker: number;
  worker_name: string;
  employee_number: string;
  date: string;
  attended: boolean;
  output_quantity: number;
  daily_wage_override: string | null;
  daily_wage: string;
  created_at: string;
  updated_at: string;
}

export interface StaffTaskTargetTier {
  target_quantity: number;
  amount: string;
}

export interface StaffTask {
  id: number;
  name: string;
  pay_basis: 'daily' | 'hourly' | 'monthly' | 'target';
  pay_basis_display: string;
  pay_rate: string;
  target_tiers: StaffTaskTargetTier[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface StaffTaskEntry {
  id: number;
  worker: number;
  worker_name: string;
  employee_number: string;
  task: number;
  task_name: string;
  date: string;
  assignment_type: 'daily' | 'permanent';
  pay_basis: StaffTask['pay_basis'];
  pay_basis_display: string;
  pay_rate: string;
  hours: string;
  target_tiers: StaffTaskTargetTier[];
  units_worked: number;
  created_at: string;
}

export interface StaffTaskAssignment {
  id: number;
  worker: number;
  worker_name: string;
  task: number;
  task_name: string;
  pay_basis: StaffTask['pay_basis'];
  pay_basis_display: string;
  pay_rate: string;
  target_tiers: StaffTaskTargetTier[];
  assigned_from: string;
  is_active: boolean;
  created_at: string;
}

export interface StaffDashboardData {
  summary: {
    current_period: string;
    active_workers: number;
    on_leave_workers: number;
    inactive_workers: number;
    gross_total: string;
    task_pay_total: string;
    withholding_total: string;
    benefits_total: string;
    net_total: string;
    run_status: 'draft' | 'scheduled' | 'paid';
    run_id: number | null;
    run_count: number;
  };
  workers: StaffMember[];
  departments: Array<{ name: string; workers: number; gross_total: string }>;
  payroll_runs: PayrollRun[];
}

export type StaffMemberInput = Omit<StaffMember, 'id' | 'employee_number' | 'pay_basis_display' | 'status_display' | 'period_days_worked' | 'period_gross' | 'period_task_pay' | 'created_at' | 'updated_at'>;

async function ensureCsrfToken() {
  if (accessCsrfToken) return;
  const response = await fetchGet(apiUrl('/access/csrf/'), { credentials: 'include' });
  if (!response.ok) throw csrfInitializationError(response);
  const csrfData = await response.json() as { csrf_token: string };
  accessCsrfToken = csrfData.csrf_token;
}

function formatApiErrorBody(body: unknown, status: number) {
  const flatten = (value: unknown, path = ''): string[] => {
    if (Array.isArray(value)) return value.flatMap((item, index) => flatten(item, path ? `${path}[${index}]` : String(index)));
    if (value && typeof value === 'object') {
      return Object.entries(value).flatMap(([key, item]) => flatten(item, path ? `${path}.${key}` : key));
    }
    if (value === null || value === undefined || value === '') return [];
    return [path && path !== 'detail' ? `${path}: ${String(value)}` : String(value)];
  };
  return flatten(body).join('; ') || `API request failed (${status})`;
}

async function request<T>(
  path: string,
  options?: RequestInit,
  confirmationMode: 'required' | 'skip' = 'required',
  retryNetworkFailures = false,
): Promise<T> {
  const method = options?.method?.toUpperCase() ?? 'GET';
  const normalizedPath = path.split('?')[0];
  const excludedPostConfirmations = [
    '/access/login/',
    '/access/logout/',
    '/account/login/',
    '/account/logout/',
    '/access/permissions/',
    '/staff/payroll-runs/generate/',
  ];
  const excludedPostConfirmationPatterns = [
    /^\/access\/users\/\d+\/force_logout\/$/,
    /^\/staff\/payroll-runs\/\d+\/mark_paid\/$/,
    /^\/notifications\/(?:\d+\/(?:read|dismiss)|read_all)\/$/,
  ];
  const requiresConfirmation = method === 'DELETE'
    || (method === 'POST'
      && !excludedPostConfirmations.includes(normalizedPath)
      && !excludedPostConfirmationPatterns.some((pattern) => pattern.test(normalizedPath)));
  const manuallyConfirmedDeletes = [
    /^\/categories\/\d+\/$/,
    /^\/products\/\d+\/$/,
    /^\/po-client\/bottle-orders\/\d+\/$/,
    /^\/po-client\/material-orders\/\d+\/$/,
  ];
  const requestIsAlreadyConfirmed = method === 'DELETE'
    && manuallyConfirmedDeletes.some((pattern) => pattern.test(normalizedPath));

  if (confirmationMode === 'required' && requiresConfirmation && !requestIsAlreadyConfirmed) {
    const resource = mutationResourceName(normalizedPath);
    const deleting = method === 'DELETE';
    const actionName = mutationActionName(normalizedPath);
    const confirmed = await requestMutationConfirmation({
      title: deleting ? `Delete ${resource}?` : `${actionName === 'save' ? 'Save' : 'Add'} ${resource}?`,
      message: deleting
        ? normalizedPath.startsWith('/expense-options/categories/')
          ? 'This removes the category from new expense forms. Existing expense records and budgets will remain unchanged.'
          : normalizedPath.startsWith('/expense-options/types/')
            ? 'This removes the type from new expense forms and spend filters. Existing expense records will remain unchanged.'
          : `This will permanently delete ${resource}. This action cannot be undone.`
        : `This will ${actionName} ${resource}. Do you want to continue?`,
      confirmLabel: deleting ? 'Delete' : actionName === 'save' ? 'Save' : 'Add',
      variant: deleting ? 'danger' : 'default',
    });
    if (!confirmed) throw new Error('Action cancelled.');
  }

  let headers = new Headers(options?.headers);
  if (!headers.has('Content-Type') && options?.body) headers.set('Content-Type', 'application/json');

  if (method !== 'GET') {
    if (!accessCsrfToken) await ensureCsrfToken();
    headers.set('X-CSRFToken', accessCsrfToken);
  }

  const response = method === 'GET'
    ? await fetchGet(apiUrl(path), { ...options, credentials: 'include', headers })
    : retryNetworkFailures
      ? await fetchWithNetworkRetries(apiUrl(path), { ...options, credentials: 'include', headers })
      : await fetch(apiUrl(path), { ...options, credentials: 'include', headers });

  if (normalizedPath !== '/access/login/' && normalizedPath !== '/account/login/') {
    await throwIfAdministratorSessionExpired(response);
  }

  if (!response.ok && method !== 'GET' && response.status === 403) {
    accessCsrfToken = '';
    await ensureCsrfToken();
    headers = new Headers(options?.headers);
    if (!headers.has('Content-Type') && options?.body) headers.set('Content-Type', 'application/json');
    headers.set('X-CSRFToken', accessCsrfToken);

    const retryResponse = await fetch(apiUrl(path), {
      ...options,
      credentials: 'include',
      headers,
    });
    if (normalizedPath !== '/access/login/' && normalizedPath !== '/account/login/') {
      await throwIfAdministratorSessionExpired(retryResponse);
    }
    if (retryResponse.ok) {
      notifySuccessfulMutation(method, normalizedPath);
      const contentType = retryResponse.headers.get('content-type') ?? '';
      if (retryResponse.status === 204) return undefined as T;
      if (contentType.includes('application/json')) return retryResponse.json() as Promise<T>;
      return undefined as T;
    }
    const finalResponse = retryResponse;
    let message = `API request failed (${finalResponse.status})`;
    try {
      message = formatApiErrorBody(await finalResponse.json(), finalResponse.status);
    } catch { /* keep HTTP status */ }
    throw new Error(message);
  }

  if (!response.ok) {
    let message = `API request failed (${response.status})`;
    try {
      message = formatApiErrorBody(await response.json(), response.status);
    } catch { /* keep HTTP status */ }
    throw new Error(message);
  }
  notifySuccessfulMutation(method, normalizedPath);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function notifySuccessfulMutation(method: string, path: string) {
  if (method === 'GET' || path.startsWith('/notifications/')) return;
  if (/^\/(?:access|account)\/(?:login|logout)\/$/.test(path)) return;
  notifyDataChanged();
}

function mutationResourceName(path: string) {
  const resources: Array<[RegExp, string]> = [
    [/\/expense-options\/types\/\d+\/$/, 'this expense type'],
    [/\/expense-options\/categories\/\d+\/$/, 'this expense category'],
    [/\/sales\/checkout\/$/, 'this sale'],
    [/\/customers\/\d+\/payments\/$/, 'this customer payment'],
    [/\/suppliers\/\d+\/payments\/$/, 'this supplier payment'],
    [/\/purchases\/\d+\/payments\/$/, 'this purchase payment'],
    [/\/staff\/attendance\/record_day\/$/, 'these attendance records'],
    [/\/staff\/task-entries\/record_day\/$/, 'these task assignments and pay records'],
    [/\/staff\/task-assignments\/$/, 'this standing task assignment'],
    [/\/staff\/payroll-runs\/[^/]+\/mark_paid\/$/, 'this payroll payment status'],
    [/\/staff\/payroll-runs\/generate\/$/, 'this payroll snapshot'],
    [/\/staff\/workers\/$/, 'this worker'],
    [/\/staff\/tasks\/$/, 'this task'],
    [/\/access\/users\/\d+\/$/, 'this user account'],
    [/\/access\/groups\/\d+\/$/, 'this access group'],
    [/\/access\/users\/$/, 'this user account'],
    [/\/access\/groups\/$/, 'this access group'],
    [/\/products\/$/, 'this product'],
    [/\/categories\/$/, 'this product category'],
    [/\/customers\/$/, 'this customer'],
    [/\/suppliers\/$/, 'this supplier'],
    [/\/expenses\/bulk-upload\/$/, 'these expense records'],
    [/\/expenses\/$/, 'this expense'],
    [/\/expense-budgets\/$/, 'this expense budget'],
    [/\/purchases\/$/, 'this purchase order'],
    [/\/po-client\/bottle-products\/$/, 'this bottle product'],
    [/\/po-client\/bottle-orders\/$/, 'this bottle order'],
    [/\/po-client\/materials\/$/, 'this material'],
    [/\/po-client\/material-orders\/$/, 'this material order'],
    [/\/movements\/$/, 'this stock movement'],
    [/\/inventory\/adjustments\/$/, 'this inventory adjustment'],
    [/\/purchases\/\d+\/receive\/$/, 'this purchase receipt'],
    [/\/po-client\/bottle-orders\/\d+\/deliver\/$/, 'this delivery'],
    [/\/po-client\/material-orders\/\d+\/receive\/$/, 'this material receipt'],
  ];
  return resources.find(([pattern]) => pattern.test(path))?.[1] ?? 'this record';
}

function mutationActionName(path: string) {
  if (/\/(record_day|checkout|payments|receive|deliver|adjustments|bulk-upload)\//.test(path)) return 'save';
  return 'add';
}

async function accountAuthRequest(path: string, payload: Record<string, string>) {
  const csrfResponse = await fetchGet(apiUrl('/access/csrf/'), { credentials: 'include' });
  if (!csrfResponse.ok) throw csrfInitializationError(csrfResponse);
  const csrfData = await csrfResponse.json() as { csrf_token: string };
  accessCsrfToken = csrfData.csrf_token;
  const result = await request<{ user: AccessUser; csrf_token: string }>(path, { method: 'POST', body: JSON.stringify(payload) });
  accessCsrfToken = result.csrf_token;
  return result;
}

export const api = {
  accountSignIn: (username: string, password: string) => accountAuthRequest('/account/login/', { username, password }),
  accountSignUp: (account: { username: string; password: string; email: string; first_name: string; last_name: string }) => accountAuthRequest('/account/register/', account),
  accountSession: () => request<{ user: AccessUser }>('/account/session/'),
  accountLogout: () => request<{ ok: boolean }>('/account/logout/', { method: 'POST', body: JSON.stringify({}) }),
  async accessLogin(username: string, password: string) {
    const csrfResponse = await fetch(apiUrl('/access/csrf/'), { credentials: 'include' });
    if (!csrfResponse.ok) throw csrfInitializationError(csrfResponse);
    const csrfData = await csrfResponse.json() as { csrf_token: string };
    accessCsrfToken = csrfData.csrf_token;
    const result = await request<{ user: AccessUser; csrf_token: string }>('/access/login/', { method: 'POST', body: JSON.stringify({ username, password }) });
    accessCsrfToken = result.csrf_token;
    return result;
  },
  async accessSession() {
    const response = await fetchGet(apiUrl('/access/csrf/'), { credentials: 'include' });
    if (!response.ok) throw csrfInitializationError(response);
    const csrf = await response.json() as { csrf_token: string };
    accessCsrfToken = csrf.csrf_token;
    return request<{ user: AccessUser }>('/access/session/');
  },
  accessLogout: () => request<{ ok: boolean }>('/access/logout/', { method: 'POST', body: JSON.stringify({}) }),
  accessDashboard: () => request<AccessDashboardData>('/access/dashboard/'),
  async downloadSystemBackup() {
    const response = await fetchGet(apiUrl('/system/backup/'), { credentials: 'include' });
    if (!response.ok) {
      const body = await response.text();
      if (isAdministratorSessionExpired(response.status, body)) {
        throw new AdministratorSessionExpiredError();
      }
      let message = `Database backup failed (HTTP ${response.status}).`;
      if (body) {
        try {
          const payload = JSON.parse(body) as { detail?: unknown };
          if (typeof payload.detail === 'string') message = payload.detail;
        } catch (cause) {
          if (!(cause instanceof SyntaxError)) throw cause;
        }
      }
      throw new Error(message);
    }
    const disposition = response.headers.get('Content-Disposition') ?? '';
    const filename = /filename="?([^";]+)"?/i.exec(disposition)?.[1] ?? 'stockpulse-database-backup.json.gz';
    return { blob: await response.blob(), filename };
  },
  async restoreSystemBackup(file: File) {
    const csrfResponse = await fetchGet(apiUrl('/access/csrf/'), { credentials: 'include' });
    if (!csrfResponse.ok) throw csrfInitializationError(csrfResponse);
    const csrfData = await csrfResponse.json() as { csrf_token: string };
    accessCsrfToken = csrfData.csrf_token;

    const form = new FormData();
    form.append('backup', file);
    let response: Response;
    try {
      response = await fetch(apiUrl('/system/backup/restore/'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'X-CSRFToken': accessCsrfToken },
        body: form,
      });
    } catch (cause) {
      if (cause instanceof TypeError) {
        throw new Error('Could not connect to the StockPulse backup API. Check that the Render service is available and try again.');
      }
      throw cause;
    }
    if (!response.ok) {
      const body = await response.text();
      if (isAdministratorSessionExpired(response.status, body)) {
        throw new AdministratorSessionExpiredError();
      }
      let message = `Database restore failed (HTTP ${response.status}).`;
      if (body) {
        try {
          message = formatApiErrorBody(JSON.parse(body) as unknown, response.status);
        } catch (cause) {
          if (!(cause instanceof SyntaxError)) throw cause;
        }
      }
      throw new Error(message);
    }
    const disposition = response.headers.get('Content-Disposition') ?? '';
    const filename = /filename="?([^";]+)"?/i.exec(disposition)?.[1] ?? 'stockpulse-pre-restore-safety-backup.json.gz';
    return {
      blob: await response.blob(),
      filename,
      restoredRecords: Number(response.headers.get('X-Restored-Record-Count') ?? 0),
    };
  },
  notifications: () => request<AppNotification[]>('/notifications/'),
  markNotificationRead: (id: number) => request<AppNotification>(`/notifications/${id}/read/`, { method: 'POST', body: JSON.stringify({}) }),
  markAllNotificationsRead: () => request<{ updated: number }>('/notifications/read_all/', { method: 'POST', body: JSON.stringify({}) }),
  dismissNotification: (id: number) => request<void>(`/notifications/${id}/dismiss/`, { method: 'POST', body: JSON.stringify({}) }),
  systemSettings: () => request<SystemSettingsData>('/settings/'),
  updateSystemSettings: (settings: Partial<SystemSettings>) =>
    request<SystemSettingsData>('/settings/', { method: 'PATCH', body: JSON.stringify({ settings }) }),
  exchangeRates: () => request<ExchangeRatesData>('/exchange-rates/'),
  accessUsers: () => request<AccessUser[]>('/access/users/'),
  createAccessUser: (user: { username: string; email: string; first_name: string; last_name: string; password: string; is_active: boolean; is_staff: boolean; is_superuser: boolean; groups: number[] }) =>
    request<AccessUser>('/access/users/', { method: 'POST', body: JSON.stringify(user) }),
  updateAccessUser: (id: number, user: Partial<Pick<AccessUser, 'username' | 'email' | 'first_name' | 'last_name' | 'is_active' | 'is_staff'>> & { groups?: number[]; password?: string }) =>
    request<AccessUser>(`/access/users/${id}/`, { method: 'PATCH', body: JSON.stringify(user) }),
  forceLogoutAccessUser: (id: number) =>
    request<{ ok: boolean; revoked_sessions: number }>(`/access/users/${id}/force_logout/`, { method: 'POST', body: JSON.stringify({}) }),
  createAccessGroup: (name: string) => request<AccessGroup>('/access/groups/', { method: 'POST', body: JSON.stringify({ name }) }),
  updateAccessGroup: (id: number, data: { name?: string }) =>
    request<AccessGroup>(`/access/groups/${id}/`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteAccessGroup: (id: number) => request<void>(`/access/groups/${id}/`, { method: 'DELETE' }),
  setGroupPermissions: (groupId: number, permissionIds: number[]) =>
    request<AccessGroup>('/access/permissions/', { method: 'POST', body: JSON.stringify({ group_id: groupId, permission_ids: permissionIds }) }),
  summary: (range = '30d') => request<DashboardSummary>(`/dashboard/summary/?range=${range}`),
  products: () => request<Product[]>('/products/'),
  categories: () => request<Category[]>('/categories/'),
  createCategory: (category: Pick<Category, 'name' | 'description'>) =>
    request<Category>('/categories/', { method: 'POST', body: JSON.stringify(category) }),
  deleteCategory: (id: number) => request<void>(`/categories/${id}/`, { method: 'DELETE' }),
  suppliers: () => request<Supplier[]>('/suppliers/'),
  movements: (days?: number, month?: string, date?: string) => {
    const params = new URLSearchParams();
    if (days) params.set('days', String(days));
    if (month) params.set('month', month);
    if (date) params.set('date', date);
    return request<StockMovement[]>(`/movements/${params.size ? `?${params}` : ''}`);
  },
  createProduct: (
    product: Pick<Product, 'name' | 'sku' | 'quantity' | 'reorder_level' | 'unit_price' | 'cost_price' | 'location'> & { category: number; supplier?: number | null },
    options?: { skipConfirmation?: boolean },
  ) => request<Product>('/products/', { method: 'POST', body: JSON.stringify(product) }, options?.skipConfirmation ? 'skip' : 'required'),
  updateProduct: (id: number, product: Partial<Pick<Product, 'name' | 'sku' | 'category' | 'supplier' | 'quantity' | 'reorder_level' | 'is_active' | 'unit_price' | 'cost_price' | 'location'>>) =>
    request<Product>(`/products/${id}/`, { method: 'PATCH', body: JSON.stringify(product) }),
  deleteProduct: (id: number) => request<void>(`/products/${id}/`, { method: 'DELETE' }),
  createMovement: (movement: Pick<StockMovement, 'product' | 'movement_type' | 'quantity' | 'note' | 'reference'>) =>
    request<StockMovement>('/movements/', { method: 'POST', body: JSON.stringify(movement) }),
  adjustInventory: (adjustment: InventoryAdjustment) =>
    request<StockMovement>('/inventory/adjustments/', { method: 'POST', body: JSON.stringify(adjustment) }),
  purchaseSummary: () => request<PurchaseSummary>('/purchases/summary/'),
  purchases: () => request<Purchase[]>('/purchases/'),
  sales: () => request<Sale[]>('/sales/'),
  createPurchase: (purchase: Pick<Purchase, 'supplier' | 'notes'> & { reference?: string; expected_delivery?: string | null; items: Array<Pick<PurchaseItem, 'product' | 'quantity' | 'unit_cost'>> }) =>
    request<Purchase>('/purchases/', { method: 'POST', body: JSON.stringify(purchase) }),
  receivePurchase: (id: number) =>
    request<Purchase>(`/purchases/${id}/receive/`, { method: 'POST', body: JSON.stringify({}) }),
  bottleProducts: () => request<BottleProduct[]>('/po-client/bottle-products/'),
  createBottleProduct: (product: Pick<BottleProduct, 'category' | 'unit' | 'unit_price'> & { inventory_product: number }) =>
    request<BottleProduct>('/po-client/bottle-products/', { method: 'POST', body: JSON.stringify(product) }),
  bottleOrders: () => request<BottleCustomerPO[]>('/po-client/bottle-orders/'),
  createBottleOrder: (order: { reference: string; customer: number; expected_delivery?: string | null; notes?: string; items: Array<{ product: number; quantity: number; unit_price: string }> }) =>
    request<BottleCustomerPO>('/po-client/bottle-orders/', { method: 'POST', body: JSON.stringify(order) }),
  deleteBottleOrder: (id: number) =>
    request<void>(`/po-client/bottle-orders/${id}/`, { method: 'DELETE' }),
  deliverBottleOrder: (id: number, delivery: { items: Array<{ purchase_order_line: number; quantity: number }>; notes?: string }) =>
    request<BottleCustomerPO>(`/po-client/bottle-orders/${id}/deliver/`, { method: 'POST', body: JSON.stringify(delivery) }),
  clientMaterials: () => request<ClientMaterial[]>('/po-client/materials/'),
  createClientMaterial: (material: Pick<ClientMaterial, 'name' | 'unit' | 'unit_price'>) =>
    request<ClientMaterial>('/po-client/materials/', { method: 'POST', body: JSON.stringify(material) }),
  clientMaterialOrders: () => request<ClientMaterialPO[]>('/po-client/material-orders/'),
  createClientMaterialOrder: (order: { reference: string; customer: number; material: number; quantity: string; unit_price: string; expected_delivery?: string | null; notes?: string }) =>
    request<ClientMaterialPO>('/po-client/material-orders/', { method: 'POST', body: JSON.stringify(order) }),
  deleteClientMaterialOrder: (id: number) =>
    request<void>(`/po-client/material-orders/${id}/`, { method: 'DELETE' }),
  receiveClientMaterialOrder: (id: number, receipt: { quantity: string; notes?: string }) =>
    request<ClientMaterialPO>(`/po-client/material-orders/${id}/receive/`, { method: 'POST', body: JSON.stringify(receipt) }),
  payPurchase: (id: number, payment: { amount: string; payment_method: Exclude<SupplierLedgerEntry['payment_method'], ''>; reference?: string; note?: string }) =>
    request<{ purchase: Purchase; ledger_entry: SupplierLedgerEntry }>(`/purchases/${id}/payments/`, {
      method: 'POST',
      body: JSON.stringify(payment),
    }),
  salesSummary: () => request<SalesSummary>('/sales/summary/'),
  checkoutSale: (sale: {
    customer?: number | null;
    customer_name: string;
    payment_method: Sale['payment_method'];
    discount_percent: string;
    cash_tendered?: string;
    items: Array<{ product: number; quantity: number; unit_price?: string }>;
  }) => request<Sale>('/sales/checkout/', { method: 'POST', body: JSON.stringify(sale) }),
  reportsSummary: (range: '1d' | '7d' | '30d' | '90d' | '180d' | '365d' | '730d' | '1825d' | '3650d' | '18250d' | '36500d' | '73000d' = '30d', month?: string, date?: string) => {
    const params = new URLSearchParams(date ? { date } : month ? { month } : { range });
    return request<ReportsSummary>(`/reports/summary/?${params}`);
  },
  expenses: (filters?: { start_date?: string; end_date?: string; category?: string; payment_method?: string; status?: string }) => {
    const params = new URLSearchParams(Object.entries(filters ?? {}).filter((entry): entry is [string, string] => Boolean(entry[1])));
    return request<Expense[]>(`/expenses/${params.size ? `?${params}` : ''}`);
  },
  expenseSummary: (month?: string) => request<ExpenseSummary>(`/expenses/summary/${month ? `?month=${month}` : ''}`),
  expenseOptions: () => request<ExpenseOptions>('/expense-options/'),
  createExpenseOption: (kind: 'category' | 'type', name: string) =>
    request<ExpenseOptions>('/expense-options/', { method: 'POST', body: JSON.stringify({ kind, name }) }),
  deleteExpenseCategory: (id: number) =>
    request<ExpenseOptions>(`/expense-options/categories/${id}/`, { method: 'DELETE' }),
  deleteExpenseType: (id: number) =>
    request<ExpenseOptions>(`/expense-options/types/${id}/`, { method: 'DELETE' }),
  balanceSheet: () => request<BalanceSheetSummary>('/expenses/balance-sheet/'),
  updateBalanceSheetAccount: (category: BalanceSheetCategory, account: Partial<Pick<BalanceSheetAccount, 'amount'>>) =>
    request<BalanceSheetAccount>(`/balance-sheet-accounts/${category}/`, { method: 'PATCH', body: JSON.stringify(account) }),
  createExpense: (expense: ExpenseInput) =>
    request<Expense>('/expenses/', { method: 'POST', body: JSON.stringify(expense) }),
  updateExpense: (id: number, expense: Partial<ExpenseInput>) =>
    request<Expense>(`/expenses/${id}/`, { method: 'PATCH', body: JSON.stringify(expense) }),
  bulkCreateExpenses: (expenses: ExpenseInput[]) =>
    request<Expense[]>('/expenses/bulk-upload/', { method: 'POST', body: JSON.stringify({ expenses }) }),
  staffDashboard: (period?: string) => request<StaffDashboardData>(`/staff/dashboard/${period ? `?period=${encodeURIComponent(period)}` : ''}`),
  staffAttendance: (period: string) => request<StaffAttendance[]>(`/staff/attendance/?period=${encodeURIComponent(period)}`),
  recordStaffAttendance: (date: string, records: Array<{ worker: number; attended: boolean; output_quantity: number; daily_wage_override?: number | null }>, skipConfirmation = false) =>
    request<StaffAttendance[]>('/staff/attendance/record_day/', { method: 'POST', body: JSON.stringify({ date, records }) }, skipConfirmation ? 'skip' : 'required', true),
  staffTasks: () => request<StaffTask[]>('/staff/tasks/'),
  createStaffTask: (task: Pick<StaffTask, 'name' | 'pay_basis' | 'pay_rate' | 'target_tiers'>) =>
    request<StaffTask>('/staff/tasks/', { method: 'POST', body: JSON.stringify(task) }),
  updateStaffTask: (id: number, task: Partial<Pick<StaffTask, 'name' | 'pay_basis' | 'pay_rate' | 'target_tiers' | 'is_active'>>) =>
    request<StaffTask>(`/staff/tasks/${id}/`, { method: 'PATCH', body: JSON.stringify(task) }),
  staffTaskAssignments: () => request<StaffTaskAssignment[]>('/staff/task-assignments/?active=true'),
  createStaffTaskAssignment: (assignment: Pick<StaffTaskAssignment, 'worker' | 'task' | 'assigned_from'>) =>
    request<StaffTaskAssignment>('/staff/task-assignments/', { method: 'POST', body: JSON.stringify(assignment) }),
  updateStaffTaskAssignment: (id: number, assignment: Partial<Pick<StaffTaskAssignment, 'is_active'>>) =>
    request<StaffTaskAssignment>(`/staff/task-assignments/${id}/`, { method: 'PATCH', body: JSON.stringify(assignment) }),
  staffTaskEntries: (period: string) => request<StaffTaskEntry[]>(`/staff/task-entries/?period=${encodeURIComponent(period)}`),
  removePermanentStaffTaskEntry: (date: string, worker: number, task: number) =>
    request<{ removed: boolean; permanent_assignment_deactivated: boolean }>('/staff/task-entries/remove_permanent/', {
      method: 'POST',
      body: JSON.stringify({ date, worker, task }),
    }),
  recordStaffTaskEntries: (date: string, records: Array<{ worker: number; task: number; hours: string; units_worked: number }>, skipConfirmation = false) =>
    request<StaffTaskEntry[]>('/staff/task-entries/record_day/', { method: 'POST', body: JSON.stringify({ date, records }) }, skipConfirmation ? 'skip' : 'required', true),
  createStaffMember: (worker: StaffMemberInput) => request<StaffMember>('/staff/workers/', { method: 'POST', body: JSON.stringify(worker) }),
  updateStaffMember: (id: number, worker: Partial<StaffMemberInput>) => request<StaffMember>(`/staff/workers/${id}/`, { method: 'PATCH', body: JSON.stringify(worker) }),
  generatePayrollRun: (period: string) => request<PayrollRun>('/staff/payroll-runs/generate/', { method: 'POST', body: JSON.stringify({ period }) }),
  markPayrollPaid: (id: number) => request<PayrollRun>(`/staff/payroll-runs/${id}/mark_paid/`, { method: 'POST', body: JSON.stringify({}) }),
  expenseBudgets: () => request<ExpenseBudget[]>('/expense-budgets/'),
  createExpenseBudget: (budget: Pick<ExpenseBudget, 'category' | 'monthly_limit' | 'cost_center' | 'manager'>) =>
    request<ExpenseBudget>('/expense-budgets/', { method: 'POST', body: JSON.stringify(budget) }),
  updateExpenseBudget: (id: number, budget: Partial<Pick<ExpenseBudget, 'monthly_limit' | 'cost_center' | 'manager'>>) =>
    request<ExpenseBudget>(`/expense-budgets/${id}/`, { method: 'PATCH', body: JSON.stringify(budget) }),
  customers: () => request<Customer[]>('/customers/'),
  createCustomer: (customer: Omit<Customer, 'id' | 'customer_code' | 'tax_exempt' | 'outstanding_balance' | 'lifetime_revenue' | 'completed_orders' | 'created_at'>) =>
    request<Customer>('/customers/', { method: 'POST', body: JSON.stringify(customer) }),
  updateCustomer: (id: number, customer: Partial<Omit<Customer, 'id' | 'customer_code' | 'tax_exempt' | 'outstanding_balance' | 'lifetime_revenue' | 'completed_orders' | 'created_at'>>) =>
    request<Customer>(`/customers/${id}/`, { method: 'PATCH', body: JSON.stringify(customer) }),
  customerDashboard: (id: number) => request<CustomerDashboardData>(`/customers/${id}/dashboard/`),
  receiveCustomerPayment: (id: number, payment: { amount: string; payment_method: Exclude<CustomerLedgerEntry['payment_method'], ''>; reference?: string; note?: string; sale?: number }) =>
    request<{ customer: Customer; ledger_entry: CustomerLedgerEntry }>(`/customers/${id}/payments/`, { method: 'POST', body: JSON.stringify(payment) }),
  supplierDashboard: (id: number) => request<SupplierDashboardData>(`/suppliers/${id}/dashboard/`),
  createSupplier: (supplier: Omit<Supplier, 'id' | 'supplier_code' | 'outstanding_balance' | 'lifetime_spend' | 'completed_orders' | 'on_time_delivery_rate' | 'created_at'>) =>
    request<Supplier>('/suppliers/', { method: 'POST', body: JSON.stringify(supplier) }),
  updateSupplier: (id: number, supplier: Partial<Omit<Supplier, 'id' | 'supplier_code' | 'outstanding_balance' | 'lifetime_spend' | 'completed_orders' | 'on_time_delivery_rate' | 'created_at'>>) =>
    request<Supplier>(`/suppliers/${id}/`, { method: 'PATCH', body: JSON.stringify(supplier) }),
  paySupplier: (id: number, payment: { amount: string; payment_method: Exclude<SupplierLedgerEntry['payment_method'], ''>; reference?: string; note?: string }) =>
    request<{ supplier: Supplier; ledger_entry: SupplierLedgerEntry }>(`/suppliers/${id}/payments/`, { method: 'POST', body: JSON.stringify(payment) }),
};

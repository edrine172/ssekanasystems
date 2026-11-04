import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowRight, Banknote, BriefcaseBusiness, CalendarDays, Check, ChevronDown,
  CircleAlert, Clock3, Eye, EyeOff, FileText, Filter, LogOut, Plus, RefreshCw,
  Search, ShieldCheck, Trash2, Users, Wallet, X,
} from 'lucide-react';
import FileActionMenu from './FileActionMenu';
import { downloadSpreadsheetWorkbook, readSpreadsheetWorkbook } from './fileFormats';
import { attendanceRecordWage } from './staffAttendance';
import {
  api, formatCurrency as currency, getCurrencyDisplay, type AccessUser, type PayrollRun,
  type StaffAttendance, type StaffDashboardData, type StaffMember, type StaffMemberInput,
  type StaffTask, type StaffTaskAssignment, type StaffTaskEntry, type StaffTaskTargetTier,
} from './api';
import { useConfirmation } from './ConfirmDialog';

type DashboardTarget = 'overview' | 'products' | 'inventory' | 'purchases' | 'pos' | 'sales' | 'reports' | 'customers' | 'suppliers' | 'expenses' | 'users' | 'settings';
type StaffFormValues = Omit<StaffMemberInput, 'hire_date'> & { hire_date: string };

const periodLabel = (period: string) => new Date(`${period}-01T00:00:00`).toLocaleDateString('en-UG', { month: 'long', year: 'numeric' });
const thisPeriod = () => { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`; };
const payrollPeriodStorageKey = 'stockpulse-payroll-period';
const payrollDateStorageKey = (period: string) => `stockpulse-payroll-date-${period}`;
const payrollWorkerStorageKey = 'stockpulse-payroll-worker';
const savedPayrollPeriod = () => {
  try {
    const period = localStorage.getItem(payrollPeriodStorageKey);
    return period && /^\d{4}-(0[1-9]|1[0-2])$/.test(period) ? period : thisPeriod();
  } catch {
    return thisPeriod();
  }
};
const savedPayrollDate = (period: string) => {
  try {
    const date = localStorage.getItem(payrollDateStorageKey(period));
    if (date && date.startsWith(`${period}-`) && /^\d{4}-\d{2}-\d{2}$/.test(date)) {
      const [, month, day] = date.split('-').map(Number);
      if (day > 0 && day <= new Date(Number(period.slice(0, 4)), month, 0).getDate()) return date;
    }
  } catch {
    return `${period}-01`;
  }
  return `${period}-01`;
};
const savedPayrollWorker = () => {
  try {
    const workerId = Number(localStorage.getItem(payrollWorkerStorageKey));
    return Number.isInteger(workerId) && workerId > 0 ? workerId : null;
  } catch {
    return null;
  }
};
const dateLabel = (date: string | null) => date ? new Date(date).toLocaleString('en-UG', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) : 'Not yet paid';
const isSunday = (date: string) => { const [year, month, day] = date.split('-').map(Number); return new Date(year, month - 1, day).getDay() === 0; };
const dailyAttendanceWage = (attended: boolean, outputQuantity: string | number, payBasis: StaffMember['pay_basis'], wageOverride = '') => {
  if (!attended || payBasis !== 'daily') return 0;
  const units = Number(outputQuantity);
  const tierWage = units >= 15 ? 7000 : units >= 12 ? 6000 : units >= 10 ? 5000 : units >= 8 ? 4000 : null;
  return tierWage ?? (wageOverride.trim() ? Number(wageOverride) : 0);
};
const dailyAttendanceTier = (date: string, outputQuantity: string | number) => {
  const units = Number(outputQuantity);
  return units >= 15 ? '15+ units' : units >= 12 ? '12–14 units' : isSunday(date)
    ? units >= 10 ? '10–11 units' : units >= 8 ? '8–9 units' : 'Below 8 units'
    : units >= 10 ? '10–11 units' : units >= 8 ? '8–9 units' : 'Below 8 units';
};
const targetTierPayout = (unitsWorked: number, tiers: StaffTaskTargetTier[]) =>
  tiers.filter((tier) => unitsWorked >= tier.target_quantity)
    .sort((first, second) => second.target_quantity - first.target_quantity)[0]?.amount ?? '0';
const targetTierDescription = (tiers: StaffTaskTargetTier[]) =>
  tiers.map((tier) => `${tier.target_quantity} units: ${currency(tier.amount)}`).join(' · ');
const taskEntryPay = (entry: StaffTaskEntry, entries: StaffTaskEntry[]) => {
  if (entry.pay_basis === 'daily') return Number(entry.pay_rate);
  if (entry.pay_basis === 'hourly') return Number(entry.pay_rate) * Number(entry.hours);
  if (entry.pay_basis === 'target') return Number(targetTierPayout(entry.units_worked, entry.target_tiers));
  const alreadyCounted = entries.some((candidate) =>
    candidate.worker === entry.worker
    && candidate.task === entry.task
    && candidate.date.slice(0, 7) === entry.date.slice(0, 7)
    && candidate.date < entry.date);
  return alreadyCounted ? 0 : Number(entry.pay_rate);
};

function WorkerForm({ worker, onClose, onSaved }: {
  worker: StaffMember | null;
  onClose: () => void;
  onSaved: (worker: StaffMemberInput) => Promise<void>;
}) {
  const [form, setForm] = useState<StaffFormValues>(() => ({
    full_name: worker?.full_name ?? '', email: worker?.email ?? '', phone: worker?.phone ?? '',
    job_title: worker?.job_title ?? '', department: worker?.department ?? 'Warehouse & Logistics',
    pay_basis: worker?.pay_basis ?? 'monthly', pay_rate: worker?.pay_rate ?? '',
    hours_per_period: worker?.hours_per_period ?? '160', withholding_percent: worker?.withholding_percent ?? '0',
    benefit_deduction: worker?.benefit_deduction ?? '0', status: worker?.status ?? 'active',
    hire_date: worker?.hire_date ?? new Date().toISOString().slice(0, 10),
  }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  function set<K extends keyof StaffFormValues>(key: K, value: StaffFormValues[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError('');
    try { await onSaved(form.pay_basis === 'daily' ? { ...form, pay_rate: '7000' } : form); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Worker details could not be saved.'); }
    finally { setSaving(false); }
  }

  return <div className="catalog-overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <form className="catalog-modal staff-worker-modal" onSubmit={(event) => void submit(event)}>
      <div className="catalog-modal-heading"><div><span className="catalog-eyebrow">PEOPLE OPERATIONS</span><h2>{worker ? 'Edit worker' : 'Add worker'}</h2><p>Maintain role, pay basis, and configured deductions.</p></div><button className="catalog-icon-button" type="button" onClick={onClose} aria-label="Close"><X size={18}/></button></div>
      <div className="catalog-form-row"><label className="catalog-field">Full name<input required maxLength={160} value={form.full_name} onChange={(event) => set('full_name', event.target.value)}/></label><label className="catalog-field">Department<input required maxLength={100} value={form.department} onChange={(event) => set('department', event.target.value)}/></label></div>
      <div className="catalog-form-row"><label className="catalog-field">Job title<input required maxLength={120} value={form.job_title} onChange={(event) => set('job_title', event.target.value)}/></label><label className="catalog-field">Work email<input type="email" value={form.email} onChange={(event) => set('email', event.target.value)}/></label></div>
      <div className="catalog-form-row"><label className="catalog-field">Phone<input value={form.phone} onChange={(event) => set('phone', event.target.value)}/></label><label className="catalog-field">Hire date<input type="date" required value={form.hire_date} onChange={(event) => set('hire_date', event.target.value)}/></label></div>
      <div className="catalog-form-row"><label className="catalog-field">Pay basis<select value={form.pay_basis} onChange={(event) => set('pay_basis', event.target.value as StaffMember['pay_basis'])}><option value="monthly">Monthly salary</option><option value="hourly">Hourly wage</option><option value="daily">Daily wage</option></select></label>{form.pay_basis === 'daily' ? <p className="staff-form-note">Monday to Saturday: 15+ units earns UGX 7,000; 12–14 earns UGX 6,000; 10–11 earns UGX 5,000; 8–9 earns UGX 4,000; below 8 earns UGX 0. Sunday: 15+ units earns UGX 7,000; 12–14 earns UGX 6,000; 10–11 earns UGX 5,000; 8–9 earns UGX 4,000; below 8 earns UGX 0.</p> : <label className="catalog-field">Pay rate (UGX)<input type="number" min="0.01" step="0.01" required value={form.pay_rate} onChange={(event) => set('pay_rate', event.target.value)}/></label>}</div>
      {form.pay_basis === 'hourly' && <label className="catalog-field">Hours per pay period<input type="number" min="0.01" step="0.25" required value={form.hours_per_period} onChange={(event) => set('hours_per_period', event.target.value)}/></label>}
      <div className="catalog-form-row"><label className="catalog-field">Configured withholding (%)<input type="number" min="0" max="100" step="0.01" value={form.withholding_percent} onChange={(event) => set('withholding_percent', event.target.value)}/></label><label className="catalog-field">Benefits deduction (UGX)<input type="number" min="0" step="0.01" value={form.benefit_deduction} onChange={(event) => set('benefit_deduction', event.target.value)}/></label></div>
      {worker && <label className="catalog-field">Employment status<select value={form.status} onChange={(event) => set('status', event.target.value as StaffMember['status'])}><option value="active">Active</option><option value="leave">On leave</option><option value="inactive">Inactive</option></select></label>}
      <p className="staff-form-note"><ShieldCheck size={13}/> Withholding is an administrator-configured estimate, not statutory tax advice.</p>
      {error && <p className="catalog-form-error">{error}</p>}
      <div className="catalog-modal-actions"><button type="button" className="catalog-button catalog-button-light" onClick={onClose}>Cancel</button><button className="catalog-button catalog-button-primary" disabled={saving}>{saving ? 'Saving…' : worker ? 'Save worker' : 'Enroll worker'}</button></div>
    </form>
  </div>;
}

function DailyAttendancePanel({ period, workers, locked, selectedWorkerId, monthlyGrossByWorker, onSelectedWorkerChange, panelRef, onPeriodChange, onSaved, onConfirmImport }: {
  period: string;
  workers: StaffMember[];
  locked: boolean;
  selectedWorkerId: number | null;
  monthlyGrossByWorker: Record<number, number>;
  onSelectedWorkerChange: (workerId: number | null) => void;
  panelRef: React.RefObject<HTMLElement>;
  onPeriodChange: (period: string) => void;
  onSaved: () => Promise<void>;
  onConfirmImport: (attendanceRows: number, activityRows: number) => Promise<boolean>;
}) {
  const [date, setDate] = useState(() => savedPayrollDate(period));
  const draftDateRef = useRef(date);
  const [workerSearch, setWorkerSearch] = useState('');
  const [attendanceRecords, setAttendanceRecords] = useState<StaffAttendance[]>([]);
  const [taskEntries, setTaskEntries] = useState<StaffTaskEntry[]>([]);
  const [availableTasks, setAvailableTasks] = useState<StaffTask[]>([]);
  const [taskRefreshToken, setTaskRefreshToken] = useState(0);
  const [drafts, setDrafts] = useState<Record<number, { attended: boolean; output_quantity: string; daily_wage_override: string }>>({});
  const [taskDrafts, setTaskDrafts] = useState<Record<number, { task: string; hours: string; units_worked: string }>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savingTaskWorkerId, setSavingTaskWorkerId] = useState<number | null>(null);
  const [workbookBusy, setWorkbookBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const workbookInputRef = useRef<HTMLInputElement>(null);
  const [year, month] = period.split('-').map(Number);
  const numberOfDays = new Date(year, month, 0).getDate();
  const periodEnd = `${period}-${String(numberOfDays).padStart(2, '0')}`;
  const periodWorkers = workers.filter((worker) => worker.status === 'active' && worker.hire_date <= periodEnd);
  const attendanceWorkers = periodWorkers.filter((worker) => worker.hire_date <= date);
  const searchTerm = workerSearch.trim().toLocaleLowerCase();
  const filteredPeriodWorkers = periodWorkers.filter((worker) =>
    !searchTerm || `${worker.full_name} ${worker.employee_number} ${worker.job_title}`.toLocaleLowerCase().includes(searchTerm));
  const filteredAttendanceWorkers = attendanceWorkers.filter((worker) =>
    !searchTerm || `${worker.full_name} ${worker.employee_number} ${worker.job_title}`.toLocaleLowerCase().includes(searchTerm));
  const dailyWageWorkers = attendanceWorkers.filter((worker) => worker.pay_basis === 'daily');
  const selectedWorker = filteredPeriodWorkers.find((worker) => worker.id === selectedWorkerId) ?? null;
  const firstWeekday = (new Date(year, month - 1, 1).getDay() + 6) % 7;
  const calendarCells: Array<number | null> = [
    ...Array.from({ length: firstWeekday }, () => null),
    ...Array.from({ length: numberOfDays }, (_, index) => index + 1),
  ];
  const recordsByDate = attendanceRecords.reduce<Record<string, StaffAttendance[]>>((grouped, record) => {
    (grouped[record.date] ??= []).push(record);
    return grouped;
  }, {});
  const workersById = new Map(workers.map((worker) => [worker.id, worker]));
  const selectedDateRecords = recordsByDate[date] ?? [];
  const selectedWorkerRecord = selectedWorker ? selectedDateRecords.find((record) => record.worker === selectedWorker.id) : undefined;
  const selectedDateTaskEntries = taskEntries.filter((entry) => entry.date === date);
  const selectedWorkerTaskEntries = selectedWorker
    ? selectedDateTaskEntries.filter((entry) => entry.worker === selectedWorker.id)
    : [];
  const selectedWorkerTaskPay = selectedWorkerTaskEntries.reduce(
    (total, entry) => total + taskEntryPay(entry, taskEntries),
    0,
  );
  const selectedWorkerAttendancePay = selectedWorker?.pay_basis === 'daily'
    && selectedWorkerRecord?.attended
    && !selectedWorkerTaskEntries.length
    ? attendanceRecordWage(selectedWorkerRecord)
    : 0;
  const selectedWorkerDayTotal = selectedWorkerTaskPay + selectedWorkerAttendancePay;
  const selectedWorkerAttendance = selectedWorker
    ? attendanceRecords.filter((record) => record.worker === selectedWorker.id).sort((first, second) => first.date.localeCompare(second.date))
    : [];
  const selectedWorkerMonthTotal = selectedWorker
    ? selectedWorker.pay_basis === 'daily'
      ? selectedWorkerAttendance.reduce((total, record) => total + (
        record.attended && !taskEntries.some((entry) => entry.worker === selectedWorker.id && entry.date === record.date)
          ? attendanceRecordWage(record)
          : 0
      ), 0) + Number(selectedWorker.period_task_pay)
      : monthlyGrossByWorker[selectedWorker.id] ?? 0
    : 0;
  const selectedWorkerDaysWorked = selectedWorkerAttendance.filter((record) => record.attended).length;
  const today = new Date().toISOString().slice(0, 10);
  const taskAssignedWorkerIds = new Set(taskEntries
    .filter((entry) => entry.date === date)
    .map((entry) => entry.worker));
  const selectedDateTaskPay = selectedDateTaskEntries.reduce(
    (total, entry) => total + taskEntryPay(entry, taskEntries),
    0,
  );
  const presentCount = attendanceWorkers.filter((worker) => drafts[worker.id]?.attended).length;
  const dailyAttendanceTotal = dailyWageWorkers.reduce((total, worker) => {
    const draft = drafts[worker.id] ?? { attended: false, output_quantity: '', daily_wage_override: '' };
    return total + (taskAssignedWorkerIds.has(worker.id)
      ? 0
      : dailyAttendanceWage(draft.attended, draft.output_quantity, worker.pay_basis, draft.daily_wage_override));
  }, 0);
  const dailyTotal = dailyAttendanceTotal + selectedDateTaskPay;
  const monthTotal = periodWorkers.filter((worker) => worker.pay_basis === 'daily').reduce((total, worker) => total + Number(worker.period_gross || 0), 0);
  const activeTasks = availableTasks.filter((task) => task.is_active);


  async function exportWorkbook(includeRecords: boolean) {
    setWorkbookBusy(true);
    setError('');
    setNotice('');
    try {
      await downloadSpreadsheetWorkbook(`stockpulse-workforce-${period}${includeRecords ? '' : '-template'}.xlsx`, [
        {
          name: 'Attendance',
          rows: [
            ['employee_number', 'worker_name', 'date', 'attended', 'output_quantity', 'daily_wage_override'],
            ...(includeRecords ? attendanceRecords.map((record) => [
              record.employee_number, record.worker_name, record.date, record.attended, record.output_quantity,
              record.daily_wage_override ?? '',
            ]) : []),
          ],
        },
        {
          name: 'Activities',
          rows: [
            ['employee_number', 'worker_name', 'date', 'task_id', 'task_name', 'hours', 'units_worked'],
            ...(includeRecords ? taskEntries.map((entry) => [
              entry.employee_number, entry.worker_name, entry.date, entry.task, entry.task_name, entry.hours, entry.units_worked,
            ]) : []),
          ],
        },
        {
          name: 'Reference',
          rows: [
            ['employee_number', 'worker_name', 'worker_id', 'task_id', 'task_name', 'pay_basis'],
            ...workers.map((worker) => [worker.employee_number, worker.full_name, worker.id, '', '', '']),
            ...availableTasks.map((task) => ['', '', '', task.id, task.name, task.pay_basis]),
          ],
        },
      ]);
      setNotice(includeRecords ? `Exported attendance and activity records for ${periodLabel(period)}.` : 'Downloaded a blank attendance and activity workbook template.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The workforce workbook could not be exported.');
    } finally {
      setWorkbookBusy(false);
    }
  }

  async function importWorkbook(file?: File) {
    if (!file) return;
    setWorkbookBusy(true);
    setError('');
    setNotice('');
    let savedAttendanceCount = 0;
    let savedActivityCount = 0;
    try {
      if (locked) throw new Error('Attendance and activities are locked because payroll has been generated for this month.');
      const sheets = await readSpreadsheetWorkbook(file);
      const attendanceSheet = sheets.find((sheet) => sheet.name.trim().toLowerCase() === 'attendance');
      const activitiesSheet = sheets.find((sheet) => sheet.name.trim().toLowerCase() === 'activities');
      if (!attendanceSheet && !activitiesSheet) throw new Error('The workbook must contain an Attendance sheet, an Activities sheet, or both.');

      function parseSheet(sheet: typeof sheets[number] | undefined, required: string[]) {
        if (!sheet) return [] as Array<{ get: (name: string) => string; rowNumber: number }>;
        const [header = [], ...rows] = sheet.rows;
        const normalize = (value: string) => value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
        const columns = new Map(header.map((value, index) => [normalize(value), index]));
        const missing = required.filter((column) => !columns.has(column));
        if (missing.length) throw new Error(`${sheet.name} is missing required columns: ${missing.join(', ')}.`);
        return rows.flatMap((row, index) => row.some((value) => value.trim()) ? [{
          rowNumber: index + 2,
          get: (name: string) => row[columns.get(name) ?? -1]?.trim() ?? '',
        }] : []);
      }

      const attendanceRows = parseSheet(attendanceSheet, ['employee_number', 'date', 'attended']);
      const activityRows = parseSheet(activitiesSheet, ['employee_number', 'date', 'task_id']);
      if (!attendanceRows.length && !activityRows.length) throw new Error('The workbook has no attendance or activity rows to import.');

      const workerByNumber = new Map(workers.map((worker) => [worker.employee_number.trim().toUpperCase(), worker]));
      const [existingAttendance, existingActivities, importTasks] = await Promise.all([
        api.staffAttendance(period),
        api.staffTaskEntries(period),
        api.staffTasks(),
      ]);
      const taskById = new Map(importTasks.map((task) => [task.id, task]));
      const importedAttendanceKeys = new Map<string, boolean>();
      const attendanceByDate = new Map<string, Array<{ worker: number; attended: boolean; output_quantity: number; daily_wage_override: number | null }>>();
      const activityByDate = new Map<string, Array<{ worker: number; task: number; hours: string; units_worked: number }>>();
      const todayDate = new Date().toISOString().slice(0, 10);

      function validateDate(value: string, sheetName: string, rowNumber: number) {
        const [yearValue, monthValue, dayValue] = value.split('-').map(Number);
        const parsed = new Date(yearValue, monthValue - 1, dayValue);
        if (!/^\d{4}-\d{2}-\d{2}$/.test(value)
          || parsed.getFullYear() !== yearValue
          || parsed.getMonth() !== monthValue - 1
          || parsed.getDate() !== dayValue) {
          throw new Error(`${sheetName} row ${rowNumber}: date must use YYYY-MM-DD.`);
        }
        if (!value.startsWith(`${period}-`)) throw new Error(`${sheetName} row ${rowNumber}: date must be in ${periodLabel(period)}.`);
        if (value > todayDate) throw new Error(`${sheetName} row ${rowNumber}: future dates cannot be imported.`);
        return value;
      }

      function findWorker(employeeNumber: string, date: string, sheetName: string, rowNumber: number) {
        const worker = workerByNumber.get(employeeNumber.trim().toUpperCase());
        if (!worker) throw new Error(`${sheetName} row ${rowNumber}: employee number "${employeeNumber}" was not found.`);
        if (worker.status !== 'active') throw new Error(`${sheetName} row ${rowNumber}: ${worker.full_name} is not active.`);
        if (worker.hire_date > date) throw new Error(`${sheetName} row ${rowNumber}: ${worker.full_name} was not employed on ${date}.`);
        return worker;
      }

      const seenAttendance = new Set<string>();
      for (const row of attendanceRows) {
        const date = validateDate(row.get('date'), 'Attendance', row.rowNumber);
        const worker = findWorker(row.get('employee_number'), date, 'Attendance', row.rowNumber);
        const key = `${date}:${worker.id}`;
        if (seenAttendance.has(key)) throw new Error(`Attendance row ${row.rowNumber}: duplicate employee and date.`);
        seenAttendance.add(key);
        const attendedValue = row.get('attended').toLowerCase();
        const attended = ['true', 'yes', '1', 'worked', 'present'].includes(attendedValue)
          ? true
          : ['false', 'no', '0', 'absent', 'did not work'].includes(attendedValue)
            ? false
            : null;
        if (attended === null) throw new Error(`Attendance row ${row.rowNumber}: attended must be Worked/Absent or true/false.`);
        if (!attended && existingActivities.some((entry) => entry.date === date && entry.worker === worker.id)) {
          throw new Error(`Attendance row ${row.rowNumber}: ${worker.full_name} already has activities recorded for ${date} and cannot be marked absent.`);
        }
        const outputValue = row.get('output_quantity').replace(/,/g, '');
        if (attended && worker.pay_basis === 'daily' && !outputValue) {
          throw new Error(`Attendance row ${row.rowNumber}: daily-paid workers need output_quantity when marked attended.`);
        }
        const outputQuantity = outputValue ? Number(outputValue) : 0;
        if (!Number.isInteger(outputQuantity) || outputQuantity < 0) throw new Error(`Attendance row ${row.rowNumber}: output_quantity must be a non-negative whole number.`);
        const overrideValue = row.get('daily_wage_override').replace(/,/g, '');
        const wageOverride = overrideValue ? Number(overrideValue) : null;
        if (wageOverride !== null && (!Number.isFinite(wageOverride) || wageOverride < 0)) throw new Error(`Attendance row ${row.rowNumber}: daily_wage_override must be a non-negative amount.`);
        if (wageOverride !== null && (!attended || worker.pay_basis !== 'daily' || outputQuantity >= 8)) {
          throw new Error(`Attendance row ${row.rowNumber}: wage overrides are only allowed for attended daily-paid workers with fewer than 8 units.`);
        }
        importedAttendanceKeys.set(key, attended);
        const group = attendanceByDate.get(date) ?? [];
        group.push({ worker: worker.id, attended, output_quantity: outputQuantity, daily_wage_override: wageOverride });
        attendanceByDate.set(date, group);
      }

      const seenActivities = new Set<string>();
      for (const row of activityRows) {
        const date = validateDate(row.get('date'), 'Activities', row.rowNumber);
        const worker = findWorker(row.get('employee_number'), date, 'Activities', row.rowNumber);
        const taskIdText = row.get('task_id');
        const taskId = Number(taskIdText);
        const task = /^\d+$/.test(taskIdText) ? taskById.get(taskId) : undefined;
        if (!task) throw new Error(`Activities row ${row.rowNumber}: task_id "${taskIdText}" was not found.`);
        const attendanceKey = `${date}:${worker.id}`;
        const importedAttended = importedAttendanceKeys.get(attendanceKey);
        const recordedAttended = existingAttendance.some((record) => record.date === date && record.worker === worker.id && record.attended);
        if (!(importedAttended ?? recordedAttended)) throw new Error(`Activities row ${row.rowNumber}: ${worker.full_name} must be marked attended for ${date}.`);
        const existingEntry = existingActivities.find((entry) => entry.date === date && entry.worker === worker.id && entry.task === task.id);
        if (!task.is_active && !existingEntry) throw new Error(`Activities row ${row.rowNumber}: ${task.name} is inactive.`);
        const key = `${date}:${worker.id}:${task.id}`;
        if (seenActivities.has(key)) throw new Error(`Activities row ${row.rowNumber}: duplicate employee, task, and date.`);
        seenActivities.add(key);
        const hoursText = row.get('hours').replace(/,/g, '');
        const hours = hoursText ? Number(hoursText) : 0;
        const unitsText = row.get('units_worked').replace(/,/g, '');
        if (task.pay_basis === 'target' && !unitsText) throw new Error(`Activities row ${row.rowNumber}: target tasks require units_worked.`);
        const unitsWorked = unitsText ? Number(unitsText) : 0;
        if (!Number.isFinite(hours) || hours < 0) throw new Error(`Activities row ${row.rowNumber}: hours must be a non-negative number.`);
        if (!Number.isInteger(unitsWorked) || unitsWorked < 0) throw new Error(`Activities row ${row.rowNumber}: units_worked must be a non-negative whole number.`);
        if (task.pay_basis === 'hourly' && hours <= 0) throw new Error(`Activities row ${row.rowNumber}: hourly tasks require hours greater than zero.`);
        const group = activityByDate.get(date) ?? [];
        group.push({ worker: worker.id, task: task.id, hours: String(hours), units_worked: unitsWorked });
        activityByDate.set(date, group);
      }

      if (!await onConfirmImport(attendanceRows.length, activityRows.length)) return;

      for (const [date, records] of [...attendanceByDate.entries()].sort(([first], [second]) => first.localeCompare(second))) {
        await api.recordStaffAttendance(date, records, true);
        savedAttendanceCount += records.length;
      }
      for (const [date, importedRecords] of [...activityByDate.entries()].sort(([first], [second]) => first.localeCompare(second))) {
        const merged = new Map(existingActivities.filter((entry) => entry.date === date).map((entry) => [
          `${entry.worker}:${entry.task}`,
          { worker: entry.worker, task: entry.task, hours: entry.hours, units_worked: entry.units_worked },
        ]));
        importedRecords.forEach((entry) => merged.set(`${entry.worker}:${entry.task}`, entry));
        await api.recordStaffTaskEntries(date, [...merged.values()], true);
        savedActivityCount += importedRecords.length;
      }

      const [updatedAttendance, updatedActivities] = await Promise.all([
        api.staffAttendance(period),
        api.staffTaskEntries(period),
      ]);
      setAttendanceRecords(updatedAttendance);
      setTaskEntries(updatedActivities);
      setTaskRefreshToken((current) => current + 1);
      await onSaved();
      setNotice(`Imported ${savedAttendanceCount} attendance and ${savedActivityCount} activity rows for ${periodLabel(period)}.`);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'The workforce workbook could not be imported.';
      const partial = savedAttendanceCount || savedActivityCount
        ? ` Import stopped after saving ${savedAttendanceCount} attendance and ${savedActivityCount} activity rows.`
        : '';
      setError(`${message}${partial}`);
    } finally {
      setWorkbookBusy(false);
      if (workbookInputRef.current) workbookInputRef.current.value = '';
    }
  }
  useEffect(() => { setDate(savedPayrollDate(period)); }, [period]);
  useEffect(() => {
    if (!date.startsWith(`${period}-`)) return;
    try {
      localStorage.setItem(payrollDateStorageKey(period), date);
    } catch {
      // The calendar still works when browser storage is unavailable.
    }
  }, [date]);

  useEffect(() => {
    if (selectedWorkerId !== null && !filteredPeriodWorkers.some((worker) => worker.id === selectedWorkerId)) {
      onSelectedWorkerChange(null);
    }
  }, [filteredPeriodWorkers, onSelectedWorkerChange, selectedWorkerId]);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError('');
    void api.staffAttendance(period).then((records) => {
      if (!current) return;
      setAttendanceRecords(records);
    }).catch((cause) => {
      if (current) setError(cause instanceof Error ? cause.message : 'Attendance could not be loaded.');
    }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [period, workers]);

  useEffect(() => {
    const dateChanged = draftDateRef.current !== date;
    draftDateRef.current = date;
    const existing = new Map<number, StaffAttendance>((recordsByDate[date] ?? []).map((record) => [record.worker, record]));
    setDrafts((current) => Object.fromEntries(attendanceWorkers.map((worker) => {
      const record = existing.get(worker.id);
      const currentDraft = current[worker.id];
      return [worker.id, dateChanged || !currentDraft ? {
        attended: record?.attended ?? false,
        output_quantity: String(record?.output_quantity ?? ''),
        daily_wage_override: record?.daily_wage_override ?? '',
      } : currentDraft];
    })));
  }, [date, attendanceRecords, workers]);

  function updateDraft(worker: StaffMember, changes: Partial<{ attended: boolean; output_quantity: string; daily_wage_override: string }>) {
    setDrafts((current) => ({
      ...current,
      [worker.id]: { attended: current[worker.id]?.attended ?? false, output_quantity: current[worker.id]?.output_quantity ?? '', daily_wage_override: current[worker.id]?.daily_wage_override ?? '', ...changes },
    }));
  }

  async function saveAttendance() {
    const missingOutput = dailyWageWorkers.some((worker) => {
      const draft = drafts[worker.id];
      return draft?.attended && draft.output_quantity.trim() === '';
    });
    if (missingOutput) { setError('Enter actual units for each attended daily-paid worker.'); return; }
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const savedRecords = await api.recordStaffAttendance(date, attendanceWorkers.map((worker) => {
        const draft = drafts[worker.id] ?? { attended: false, output_quantity: '', daily_wage_override: '' };
        const outputQuantity = draft.attended && worker.pay_basis === 'daily' ? Number(draft.output_quantity) || 0 : 0;
        return {
          worker: worker.id,
          attended: draft.attended,
          output_quantity: outputQuantity,
          daily_wage_override: draft.attended && worker.pay_basis === 'daily' && outputQuantity < 8 && draft.daily_wage_override.trim()
            ? Number(draft.daily_wage_override)
            : null,
        };
      }));
      setAttendanceRecords((current) => [...current.filter((record) => record.date !== date), ...savedRecords]);
      await onSaved();
      setNotice(`Attendance saved for ${new Date(`${date}T00:00:00`).toLocaleDateString('en-UG', { day: 'numeric', month: 'long' })}.`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Attendance could not be saved.'); }
    finally { setSaving(false); }
  }

  async function assignTaskToWorker(worker: StaffMember) {
    const attendance = attendanceRecords.find((record) => record.worker === worker.id && record.date === date && record.attended);
    const attendanceDraft = drafts[worker.id] ?? { attended: false, output_quantity: '', daily_wage_override: '' };
    const assignment = taskDrafts[worker.id];
    const task = activeTasks.find((item) => item.id === Number(assignment?.task));
    if (!attendanceDraft.attended || !task) {
      setError('Mark the worker as attended before assigning a task.');
      return;
    }
    if (worker.pay_basis === 'daily' && attendanceDraft.output_quantity.trim() === '') {
      setError('Enter actual units for this daily-paid worker before assigning a task.');
      return;
    }
    if (task.pay_basis === 'hourly' && (!Number.isFinite(Number(assignment.hours)) || Number(assignment.hours) <= 0)) {
      setError('Enter hours worked for this hourly task.');
      return;
    }
    if (task.pay_basis === 'target' && (assignment.units_worked.trim() === '' || !Number.isInteger(Number(assignment.units_worked)) || Number(assignment.units_worked) < 0)) {
      setError('Enter the number of units completed for this target-based task.');
      return;
    }
    if (taskEntries.some((entry) => entry.date === date && entry.worker === worker.id && entry.task === task.id)) {
      setError(`${worker.full_name} is already assigned to ${task.name} on this date.`);
      return;
    }
    setSavingTaskWorkerId(worker.id);
    setError('');
    setNotice('');
    try {
      if (!attendance) {
        const outputQuantity = worker.pay_basis === 'daily' ? Number(attendanceDraft.output_quantity) || 0 : 0;
        const savedAttendance = await api.recordStaffAttendance(date, [{
          worker: worker.id,
          attended: true,
          output_quantity: outputQuantity,
          daily_wage_override: worker.pay_basis === 'daily'
            && outputQuantity < 8
            && attendanceDraft.daily_wage_override.trim()
            ? Number(attendanceDraft.daily_wage_override)
            : null,
        }]);
        setAttendanceRecords((current) => [
          ...current.filter((record) => record.date !== date || record.worker !== worker.id),
          ...savedAttendance,
        ]);
      }
      const existingEntries = (await api.staffTaskEntries(period)).filter((entry) => entry.date === date);
      if (existingEntries.some((entry) => entry.worker === worker.id && entry.task === task.id)) {
        setError(`${worker.full_name} is already assigned to ${task.name} on this date.`);
        return;
      }
      const savedEntries = await api.recordStaffTaskEntries(date, [
        ...existingEntries.map((entry) => ({
          worker: entry.worker,
          task: entry.task,
          hours: entry.hours,
          units_worked: entry.units_worked,
        })),
        {
          worker: worker.id,
          task: task.id,
          hours: task.pay_basis === 'hourly' ? assignment.hours : '0',
          units_worked: task.pay_basis === 'target' ? Number(assignment.units_worked) : 0,
        },
      ]);
      setTaskEntries((current) => [...current.filter((entry) => entry.date !== date), ...savedEntries]);
      setTaskRefreshToken((current) => current + 1);
      setTaskDrafts((current) => ({ ...current, [worker.id]: { task: '', hours: '', units_worked: '' } }));
      await onSaved();
      setNotice(`${attendance ? '' : 'Attendance saved. '}${task.name} assigned to ${worker.full_name} for this date.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Task could not be assigned to this worker.');
    } finally {
      setSavingTaskWorkerId(null);
    }
  }

  return <>
  <section className="staff-attendance-panel" ref={panelRef}>
    <div className="staff-section-heading">
      <div><span className="staff-section-icon"><CalendarDays size={14}/></span><div><h2>Daily attendance &amp; wages</h2><p>{selectedWorker ? `${selectedWorker.full_name} · ${selectedWorker.pay_basis === 'daily' ? `month to date ${currency(selectedWorkerMonthTotal)}` : selectedWorker.pay_basis_display}` : `Daily wages month to date: ${currency(monthTotal)}`}</p></div></div>
      <div className="staff-attendance-header-actions"><label className="staff-attendance-month-select"><span>Attendance month</span><input aria-label="Select attendance month and year" type="month" value={period} onChange={(event) => { if (event.target.value) onPeriodChange(event.target.value); }}/></label><div className="staff-attendance-selected-date"><span>Selected day</span><strong>{new Date(`${date}T00:00:00`).toLocaleDateString('en-UG', { weekday: 'long', day: 'numeric', month: 'long' })}</strong></div></div>
    </div>
    <div className="staff-attendance-file-toolbar">
      <FileActionMenu label="Excel workbook" direction="files" options={[
        { label: 'Import attendance and activities', direction: 'import', disabled: locked || workbookBusy, onSelect: () => workbookInputRef.current?.click() },
        { label: 'Export current month', direction: 'export', disabled: workbookBusy || (!attendanceRecords.length && !taskEntries.length), onSelect: () => void exportWorkbook(true) },
        { label: 'Download blank template', direction: 'export', disabled: workbookBusy, onSelect: () => void exportWorkbook(false) },
      ]}/>
      <input ref={workbookInputRef} className="catalog-hidden" type="file" accept=".xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel" onChange={(event) => void importWorkbook(event.target.files?.[0])}/>
      <span>{workbookBusy ? 'Processing workbook…' : `Workbook period: ${periodLabel(period)} · existing rows are preserved`}</span>
    </div>
    <div className="staff-attendance-summary"><span>{selectedWorker ? selectedWorkerRecord ? `${selectedWorker.full_name}: ${selectedWorkerRecord.attended ? 'Worked' : 'Did not work'} on this date` : selectedWorker.hire_date > date ? `${selectedWorker.full_name} was not employed yet` : `No attendance entry for ${selectedWorker.full_name} on this date` : selectedDateRecords.length ? `${presentCount} of ${attendanceWorkers.length} workers marked present` : 'Attendance has not been recorded for this day'}</span><strong>{currency(selectedWorker ? selectedWorkerDayTotal : dailyTotal)} for this day{(selectedWorker ? selectedWorkerTaskPay : selectedDateTaskPay) > 0 && <small>{currency(selectedWorker ? selectedWorkerTaskPay : selectedDateTaskPay)} task pay included</small>}</strong></div>
    <label className="staff-worker-search"><Search size={14}/><input type="search" value={workerSearch} onChange={(event) => setWorkerSearch(event.target.value)} placeholder="Search workers by name or employee number" aria-label="Search workers by name or employee number"/>{workerSearch && <button type="button" onClick={() => setWorkerSearch('')} aria-label="Clear worker search"><X size={13}/></button>}</label>
    <div className="staff-attendance-workers" role="group" aria-label="Select a worker calendar"><button type="button" className={!selectedWorkerId ? 'is-selected' : ''} aria-pressed={!selectedWorkerId} onClick={() => onSelectedWorkerChange(null)}>All workers</button>{filteredPeriodWorkers.map((worker) => <button type="button" key={worker.id} className={selectedWorkerId === worker.id ? 'is-selected' : ''} aria-pressed={selectedWorkerId === worker.id} onClick={() => onSelectedWorkerChange(worker.id)}><strong>{worker.full_name}</strong><small>{worker.job_title}</small></button>)}{searchTerm && !filteredPeriodWorkers.length && <span className="staff-worker-search-empty">No workers found.</span>}</div>
    {selectedWorker && <section className="staff-worker-month-earnings" aria-label={`${selectedWorker.full_name} earnings for ${periodLabel(period)}`}>
      <div className="staff-worker-month-total"><span><small>{selectedWorker.pay_basis === 'daily' ? 'EARNED THIS MONTH' : 'MONTHLY PAYROLL GROSS'} · {periodLabel(period)}</small><strong>{currency(selectedWorkerMonthTotal)}</strong></span><span>{selectedWorker.pay_basis === 'daily' ? `${selectedWorkerDaysWorked} paid work ${selectedWorkerDaysWorked === 1 ? 'day' : 'days'}` : `${selectedWorker.pay_basis_display} · payroll gross`}</span></div>
      {selectedWorker.pay_basis !== 'daily' && <p className="staff-worker-month-note">This worker is not paid by the day. Daily attendance is listed below; assigned task earnings are shown for each recorded date.</p>}
      <div className="staff-worker-earnings-scroll"><table className="staff-worker-earnings"><thead><tr><th>DATE</th><th>ATTENDANCE</th><th>UNITS</th><th>SUPERVISOR OVERRIDE</th><th>DAILY EARNINGS</th></tr></thead><tbody>
        {selectedWorkerAttendance.map((record) => {
          const workerDayTasks = taskEntries.filter((entry) =>
            entry.worker === selectedWorker.id && entry.date === record.date);
          const taskPay = workerDayTasks.reduce(
            (total, entry) => total + taskEntryPay(entry, taskEntries),
            0,
          );
          const dailyEarnings = workerDayTasks.length
            ? taskPay
            : selectedWorker.pay_basis === 'daily'
              ? attendanceRecordWage(record)
              : null;
          return <tr key={record.id}>
            <td>{new Date(`${record.date}T00:00:00`).toLocaleDateString('en-UG', { weekday: 'short', day: 'numeric', month: 'short' })}</td>
            <td>{record.attended ? 'Worked' : 'Did not work'}</td>
            <td>{record.attended && selectedWorker.pay_basis === 'daily' ? record.output_quantity.toLocaleString() : '—'}</td>
            <td>{record.daily_wage_override === null ? '—' : currency(record.daily_wage_override)}</td>
            <td>{dailyEarnings === null ? 'Not calculated' : <>
              {currency(dailyEarnings)}
              {workerDayTasks.length > 0 && <small>{workerDayTasks.map((entry) => `${entry.task_name}: ${currency(taskEntryPay(entry, taskEntries))}`).join(' · ')}</small>}
            </>}</td>
          </tr>;
        })}
        {!selectedWorkerAttendance.length && <tr><td colSpan={5} className="staff-worker-earnings-empty">No attendance has been recorded for this worker in {periodLabel(period)}.</td></tr>}
      </tbody></table></div>
    </section>}
    <div className="staff-calendar" aria-label={`Attendance calendar for ${periodLabel(period)}`}>
      <div className="staff-calendar-weekdays" aria-hidden="true">{['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((weekday) => <span key={weekday}>{weekday}</span>)}</div>
      <div className="staff-calendar-grid">{calendarCells.map((day, index) => {
        if (day === null) return <span className="staff-calendar-blank" key={`blank-${index}`}/>;
        const dayDate = `${period}-${String(day).padStart(2, '0')}`;
        const records = recordsByDate[dayDate] ?? [];
        const workerRecord = selectedWorker ? records.find((record) => record.worker === selectedWorker.id) : undefined;
        const dayPresent = records.filter((record) => record.attended).length;
        const dayTaskEntries = taskEntries.filter((entry) =>
          entry.date === dayDate && (!selectedWorker || entry.worker === selectedWorker.id));
        const taskTotal = dayTaskEntries.reduce((sum, entry) => sum + taskEntryPay(entry, taskEntries), 0);
        const taskWorkerIds = new Set(dayTaskEntries.map((entry) => entry.worker));
        const attendanceTotal = records.reduce((sum, record) => {
          if (!record.attended || taskWorkerIds.has(record.worker)) return sum;
          const worker = workersById.get(record.worker);
          return sum + (worker
            ? attendanceRecordWage(record)
            : Number(record.daily_wage));
        }, 0);
        const selectedAttendanceTotal = workerRecord?.attended && selectedWorker && !taskWorkerIds.has(selectedWorker.id)
          ? attendanceRecordWage(workerRecord)
          : 0;
        const dayTotal = (selectedWorker ? selectedAttendanceTotal : attendanceTotal) + taskTotal;
        const workerStatus = workerRecord ? workerRecord.attended ? 'Worked' : 'Did not work' : selectedWorker?.hire_date && selectedWorker.hire_date > dayDate ? 'Not employed' : 'No entry';
        const statusClass = selectedWorker ? workerRecord ? workerRecord.attended ? 'is-worked' : 'is-absent' : selectedWorker.hire_date > dayDate ? 'is-not-employed' : 'is-unrecorded' : records.length ? 'has-records' : '';
        const accessibleStatus = selectedWorker
          ? `${selectedWorker.full_name}: ${workerStatus}, ${currency(dayTotal)} recorded pay, ${currency(taskTotal)} task pay`
          : `${dayPresent} of ${attendanceWorkers.length} present, ${currency(dayTotal)} recorded pay, ${currency(taskTotal)} task pay`;
        return <button className={`staff-calendar-day ${date === dayDate ? 'is-selected' : ''} ${statusClass}`} type="button" key={dayDate} disabled={dayDate > today} aria-pressed={date === dayDate} aria-label={`${new Date(`${dayDate}T00:00:00`).toLocaleDateString('en-UG', { day: 'numeric', month: 'long' })}: ${accessibleStatus}`} onClick={() => setDate(dayDate)}>
          <strong>{day}</strong>{selectedWorker ? <><span>{workerStatus}</span>{workerRecord?.attended && <small>{workerRecord.output_quantity} units · {currency(workerRecord.daily_wage)}</small>}{dayTaskEntries.length > 0 && <small className="staff-calendar-task-pay">{dayTaskEntries.length} task{dayTaskEntries.length === 1 ? '' : 's'} · {currency(taskTotal)}</small>}</> : records.length || dayTaskEntries.length ? <><span>{dayPresent}/{attendanceWorkers.length} present</span><small>{currency(dayTotal)} total pay</small>{dayTaskEntries.length > 0 && <small className="staff-calendar-task-pay">Tasks · {currency(taskTotal)}</small>}</> : <span className="staff-calendar-empty">No entries</span>}
        </button>;
      })}</div>
    </div>
    {error && <div className="staff-message is-error"><CircleAlert size={14}/><span>{error}</span></div>}
    {notice && <div className="staff-message is-success"><Check size={14}/><span>{notice}</span></div>}
    {loading && <div className="staff-history-empty">Loading attendance records…</div>}
    {filteredAttendanceWorkers.length ? <div className="catalog-table-scroll"><table className="catalog-table staff-attendance-table"><thead><tr><th>WORKER</th><th>ATTENDANCE</th><th>ACTUAL UNITS</th><th>ASSIGN TASK</th><th>CALCULATED WAGE ({getCurrencyDisplay().currency})</th></tr></thead><tbody>{filteredAttendanceWorkers.map((worker) => {
      const draft = drafts[worker.id] ?? { attended: false, output_quantity: '', daily_wage_override: '' };
      const hasRecord = selectedDateRecords.some((record) => record.worker === worker.id);
      const workerTaskEntries = taskEntries.filter((entry) => entry.date === date && entry.worker === worker.id);
      const hasTaskAssignment = workerTaskEntries.length > 0;
      const taskPay = workerTaskEntries.reduce((total, entry) => total + taskEntryPay(entry, taskEntries), 0);
      const wage = hasTaskAssignment ? 0 : dailyAttendanceWage(draft.attended, draft.output_quantity, worker.pay_basis, draft.daily_wage_override);
      const needsSupervisorOverride = worker.pay_basis === 'daily' && draft.attended && Number(draft.output_quantity) < 8 && !hasTaskAssignment;
      const taskDraft = taskDrafts[worker.id] ?? { task: '', hours: '', units_worked: '' };
      const assignedTaskIds = new Set(workerTaskEntries.map((entry) => entry.task));
      const assignableTasks = activeTasks.filter((task) => !assignedTaskIds.has(task.id));
      const selectedTask = activeTasks.find((task) => task.id === Number(taskDraft.task));
      return <tr key={worker.id} className={selectedWorkerId === worker.id ? 'is-selected-worker' : ''}>
        <td><button type="button" className="staff-attendance-worker-link" aria-pressed={selectedWorkerId === worker.id} onClick={() => onSelectedWorkerChange(worker.id)}><strong>{worker.full_name}</strong><small>{worker.employee_number} · {worker.job_title}</small></button></td>
        <td><label className="staff-attendance-check"><input type="checkbox" checked={draft.attended} disabled={locked} onChange={(event) => updateDraft(worker, { attended: event.target.checked })}/><span>{hasRecord ? draft.attended ? 'Worked' : 'Did not work' : draft.attended ? 'Worked (unsaved)' : 'No entry'}</span></label></td>
        <td>{worker.pay_basis === 'daily' ? <input className="staff-attendance-wage" type="number" min="0" step="1" aria-label={`${worker.full_name} actual units completed on ${date}`} value={draft.output_quantity} placeholder="Units completed" disabled={!draft.attended || locked} onChange={(event) => updateDraft(worker, { output_quantity: event.target.value, daily_wage_override: Number(event.target.value) < 8 ? draft.daily_wage_override : '' })}/> : <span className="staff-attendance-not-applicable">Attendance only</span>}</td>
        <td>
          <div className="staff-inline-task">
            <label className="catalog-field"><span>Task</span><select aria-label={`Task to assign to ${worker.full_name}`} value={taskDraft.task} disabled={locked || !draft.attended || savingTaskWorkerId === worker.id || !assignableTasks.length} onChange={(event) => { const task = activeTasks.find((item) => item.id === Number(event.target.value)); setTaskDrafts((current) => ({ ...current, [worker.id]: { task: event.target.value, hours: task?.pay_basis === 'hourly' ? '1' : '0', units_worked: '' } })); }}><option value="">{!draft.attended ? 'Mark attended first' : !assignableTasks.length ? assignedTaskIds.size ? 'All tasks assigned' : 'No active tasks' : 'Choose task'}</option>{assignableTasks.map((task) => <option key={task.id} value={task.id}>{task.name} · {task.pay_basis_display}{task.pay_basis === 'target' ? `: ${targetTierDescription(task.target_tiers)}` : ` · ${currency(task.pay_rate)}`}</option>)}</select></label>
            {selectedTask?.pay_basis === 'hourly' && <label className="catalog-field"><span>Hours</span><input type="number" min="0.01" step="0.25" aria-label={`Hours for ${selectedTask.name} assigned to ${worker.full_name}`} value={taskDraft.hours} disabled={locked || savingTaskWorkerId === worker.id} onChange={(event) => setTaskDrafts((current) => ({ ...current, [worker.id]: { ...taskDraft, hours: event.target.value } }))}/></label>}
            {selectedTask?.pay_basis === 'target' && <label className="catalog-field"><span>Units completed ({targetTierDescription(selectedTask.target_tiers)})</span><input type="number" min="0" step="1" required aria-label={`Units completed for ${selectedTask.name} assigned to ${worker.full_name}`} value={taskDraft.units_worked} disabled={locked || savingTaskWorkerId === worker.id} onChange={(event) => setTaskDrafts((current) => ({ ...current, [worker.id]: { ...taskDraft, units_worked: event.target.value } }))}/></label>}
            <button type="button" className="catalog-button catalog-button-light" disabled={locked || !draft.attended || !selectedTask || savingTaskWorkerId === worker.id} onClick={() => void assignTaskToWorker(worker)}>{savingTaskWorkerId === worker.id ? 'Assigning…' : 'Assign'}</button>
          </div>
          {workerTaskEntries.map((entry) => <small className="staff-inline-task-assigned" key={entry.id}>{entry.task_name} assigned</small>)}
        </td>
        <td>{worker.pay_basis === 'daily' ? <span className="staff-attendance-calculated-wage"><strong>{currency(hasTaskAssignment ? taskPay : wage)}</strong><small>{hasTaskAssignment ? 'Assigned task pay only' : dailyAttendanceTier(date, draft.output_quantity)}</small></span> : <span className="staff-attendance-not-applicable">—</span>}{needsSupervisorOverride && <label className="staff-attendance-override">Supervisor override (UGX)<input type="number" min="0" step="0.01" aria-label={`${worker.full_name} supervisor wage override for ${date}`} placeholder="0 = no override" value={draft.daily_wage_override} disabled={locked} onChange={(event) => updateDraft(worker, { daily_wage_override: event.target.value })}/></label>}</td>
      </tr>;
    })}</tbody></table></div> : attendanceWorkers.length ? <div className="staff-history-empty">No workers match “{workerSearch}”.</div> : <div className="staff-history-empty">Add an active worker to record attendance.</div>}
    <div className="staff-attendance-footer"><span>{locked ? 'Attendance is locked because payroll has been generated for this month.' : 'Daily-paid workers’ attendance wages are totaled into payroll.'}</span><button className="catalog-button catalog-button-primary" onClick={() => void saveAttendance()} disabled={!attendanceWorkers.length || loading || saving || locked || date > today}>{saving ? 'Saving…' : 'Save attendance'}</button></div>
  </section>
  <TaskPayPanel period={period} date={date} workers={workers} attendanceRecords={attendanceRecords} locked={locked} refreshToken={taskRefreshToken} onSaved={onSaved} onEntriesChange={setTaskEntries} onTasksChange={setAvailableTasks}/>
  </>;
}

function TaskPayPanel({ period, date, workers, attendanceRecords, locked, refreshToken, onSaved, onEntriesChange, onTasksChange }: {
  period: string;
  date: string;
  workers: StaffMember[];
  attendanceRecords: StaffAttendance[];
  locked: boolean;
  refreshToken: number;
  onSaved: () => Promise<void>;
  onEntriesChange: (entries: StaffTaskEntry[]) => void;
  onTasksChange: (tasks: StaffTask[]) => void;
}) {
  const [tasks, setTasks] = useState<StaffTask[]>([]);
  const [permanentAssignments, setPermanentAssignments] = useState<StaffTaskAssignment[]>([]);
  const [entries, setEntries] = useState<StaffTaskEntry[]>([]);
  const [drafts, setDrafts] = useState<Array<{ worker: string; task: string; hours: string; units_worked: string }>>([]);
  const [taskName, setTaskName] = useState('');
  const [taskBasis, setTaskBasis] = useState<StaffTask['pay_basis']>('daily');
  const [taskRate, setTaskRate] = useState('');
  const [taskTargetTiers, setTaskTargetTiers] = useState<Array<{ target_quantity: string; amount: string }>>([]);
  const [permanentWorker, setPermanentWorker] = useState('');
  const [permanentTask, setPermanentTask] = useState('');
  const [editingTaskId, setEditingTaskId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [recordsLoaded, setRecordsLoaded] = useState(false);
  const [loadVersion, setLoadVersion] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const today = new Date().toISOString().slice(0, 10);
  const activeWorkers = workers.filter((worker) => worker.status === 'active' && worker.hire_date <= new Date().toISOString().slice(0, 10));
  const attendedWorkerIds = new Set(attendanceRecords.filter((record) => record.date === date && record.attended).map((record) => record.worker));
  const eligibleWorkers = activeWorkers.filter((worker) => worker.hire_date <= date && attendedWorkerIds.has(worker.id));
  const dayEntries = entries.filter((entry) => entry.date === date);
  const monthEntries = entries.filter((entry) => entry.date.slice(0, 7) === period);
  const assignedDateEarnings = dayEntries.reduce((total, entry) => total + taskEntryPay(entry, entries), 0);
  const monthlyTaskRates = new Map<string, number>();
  for (const entry of monthEntries) {
    if (entry.pay_basis === 'monthly') {
      const key = `${entry.worker}:${entry.task}`;
      if (!monthlyTaskRates.has(key)) monthlyTaskRates.set(key, Number(entry.pay_rate));
    }
  }
  const selectedMonthTaskPay = monthEntries.reduce((total, entry) => {
    if (entry.pay_basis === 'daily') return total + Number(entry.pay_rate);
    if (entry.pay_basis === 'hourly') return total + Number(entry.pay_rate) * Number(entry.hours);
    if (entry.pay_basis === 'target') return total + Number(targetTierPayout(entry.units_worked, entry.target_tiers));
    return total;
  }, 0) + [...monthlyTaskRates.values()].reduce((total, rate) => total + rate, 0);
  const activeTasks = tasks.filter((task) => task.is_active);
  const selectedPermanentWorker = permanentWorker || String(activeWorkers[0]?.id ?? '');
  const selectedPermanentTask = permanentTask || String(activeTasks[0]?.id ?? '');
  const hasAvailableAssignment = eligibleWorkers.some((worker) => activeTasks.some((task) =>
    !dayEntries.some((entry) => entry.worker === worker.id && entry.task === task.id)
    && !drafts.some((row) => Number(row.worker) === worker.id && Number(row.task) === task.id)));

  useEffect(() => { onEntriesChange(entries); }, [entries, onEntriesChange]);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setRecordsLoaded(false);
    setError('');
    void Promise.all([api.staffTasks(), api.staffTaskEntries(period), api.staffTaskAssignments()])
      .then(([taskRows, entryRows, assignmentRows]) => {
        if (!current) return;
        setTasks(taskRows);
        onTasksChange(taskRows);
        setEntries(entryRows);
        setPermanentAssignments(assignmentRows);
        setRecordsLoaded(true);
      })
      .catch((cause) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Task pay records could not be loaded.');
      })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [onTasksChange, period, loadVersion]);

  useEffect(() => {
    if (!attendanceRecords.some((record) => record.date === date)) return;
    let current = true;
    void api.staffTaskEntries(period).then((entryRows) => {
      if (current) setEntries(entryRows);
    }).catch((cause) => {
      if (current) setError(cause instanceof Error ? cause.message : 'Task pay records could not be refreshed.');
    });
    return () => { current = false; };
  }, [attendanceRecords, date, period, refreshToken]);

  useEffect(() => {
    setDrafts(dayEntries.map((entry) => ({
      worker: String(entry.worker),
      task: String(entry.task),
      hours: entry.hours,
      units_worked: String(entry.units_worked),
    })));
  }, [date, entries]);

  function resetTaskForm() {
    setEditingTaskId(null);
    setTaskName('');
    setTaskBasis('daily');
    setTaskRate('');
    setTaskTargetTiers([]);
  }

  function updateTargetTier(index: number, changes: Partial<{ target_quantity: string; amount: string }>) {
    setTaskTargetTiers((current) => current.map((tier, tierIndex) =>
      tierIndex === index ? { ...tier, ...changes } : tier));
  }

  async function saveTask(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (taskBasis === 'target' && (
      !taskTargetTiers.length
      || taskTargetTiers.some((tier) =>
        tier.target_quantity.trim() === ''
        || !Number.isInteger(Number(tier.target_quantity))
        || Number(tier.target_quantity) <= 0
        || tier.amount.trim() === ''
        || !Number.isFinite(Number(tier.amount))
        || Number(tier.amount) <= 0)
      || new Set(taskTargetTiers.map((tier) => Number(tier.target_quantity))).size !== taskTargetTiers.length
    )) {
      setError('Enter a unique positive unit target and payout amount for each tier.');
      return;
    }
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const payload = {
        name: taskName.trim(),
        pay_basis: taskBasis,
        pay_rate: taskBasis === 'target'
          ? String(Math.max(...taskTargetTiers.map((tier) => Number(tier.amount) || 0)))
          : taskRate,
        target_tiers: taskBasis === 'target'
          ? taskTargetTiers.map((tier) => ({ target_quantity: Number(tier.target_quantity), amount: tier.amount }))
          : [],
      };
      if (editingTaskId) await api.updateStaffTask(editingTaskId, payload);
      else await api.createStaffTask(payload);
      const refreshedTasks = await api.staffTasks();
      setTasks(refreshedTasks);
      onTasksChange(refreshedTasks);
      setEntries(await api.staffTaskEntries(period));
      await onSaved();
      resetTaskForm();
      setNotice(editingTaskId ? 'Task pay details updated.' : 'Task and pay details added.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Task pay details could not be saved.');
    } finally {
      setSaving(false);
    }
  }

  function editTask(task: StaffTask) {
    setEditingTaskId(task.id);
    setTaskName(task.name);
    setTaskBasis(task.pay_basis);
    setTaskRate(task.pay_rate);
    setTaskTargetTiers(task.target_tiers.map((tier) => ({
      target_quantity: String(tier.target_quantity),
      amount: String(tier.amount),
    })));
  }

  async function setTaskActive(task: StaffTask, isActive: boolean) {
    setSaving(true);
    setError('');
    setNotice('');
    try {
      await api.updateStaffTask(task.id, { is_active: isActive });
      const refreshedTasks = await api.staffTasks();
      setTasks(refreshedTasks);
      onTasksChange(refreshedTasks);
      setNotice(isActive ? 'Task activated.' : 'Task deactivated. Existing task pay records are unchanged.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : `Task could not be ${isActive ? 'activated' : 'deactivated'}.`);
    } finally {
      setSaving(false);
    }
  }

  function addAssignment() {
    const assignment = eligibleWorkers.flatMap((worker) => activeTasks.map((task) => ({ worker, task })))
      .find(({ worker, task }) =>
        !dayEntries.some((entry) => entry.worker === worker.id && entry.task === task.id)
        && !drafts.some((row) => Number(row.worker) === worker.id && Number(row.task) === task.id));
    if (!assignment) return;
    const { worker, task } = assignment;
    setDrafts((current) => [...current, {
      worker: String(worker.id),
      task: String(task.id),
      hours: task.pay_basis === 'hourly' ? '1' : '0',
      units_worked: '0',
    }]);
  }

  function updateAssignment(index: number, changes: Partial<{ worker: string; task: string; hours: string; units_worked: string }>) {
    setDrafts((current) => current.map((row, rowIndex) => {
      if (rowIndex !== index) return row;
      const next = { ...row, ...changes };
      if (changes.task) {
        const task = tasks.find((item) => item.id === Number(changes.task));
        next.hours = task?.pay_basis === 'hourly' ? '1' : '0';
        next.units_worked = '0';
      }
      return next;
    }));
  }

  async function assignPermanentTask() {
    const workerId = Number(selectedPermanentWorker);
    const taskId = Number(selectedPermanentTask);
    if (!workerId || !taskId) {
      setError('Choose a worker and task before assigning.');
      return;
    }
    setSaving(true);
    setError('');
    setNotice('');
    try {
      await api.createStaffTaskAssignment({ worker: workerId, task: taskId, assigned_from: date });
      setPermanentAssignments(await api.staffTaskAssignments());
      setEntries(await api.staffTaskEntries(period));
      setNotice(`Task assigned from ${new Date(`${date}T00:00:00`).toLocaleDateString('en-UG', { day: 'numeric', month: 'long', year: 'numeric' })}. Pay will be recorded for attended days from this date.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Permanent task assignment could not be added.');
    } finally {
      setSaving(false);
    }
  }

  async function removePermanentTaskEntry(workerId: number, taskId: number, workerName: string, taskName: string) {
    setSaving(true);
    setError('');
    setNotice('');
    try {
      await api.removePermanentStaffTaskEntry(date, workerId, taskId);
      const [assignments, taskEntries] = await Promise.all([
        api.staffTaskAssignments(),
        api.staffTaskEntries(period),
      ]);
      setPermanentAssignments(assignments);
      setEntries(taskEntries);
      await onSaved();
      setNotice(`${workerName}'s ${taskName} task was removed for ${date}. Earlier task pay records are unchanged.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Permanent task assignment could not be removed.');
    } finally {
      setSaving(false);
    }
  }

  async function removePermanentAssignment(assignment: StaffTaskAssignment) {
    const datedEntry = dayEntries.find((entry) =>
      entry.worker === assignment.worker
      && entry.task === assignment.task
      && entry.assignment_type === 'permanent');
    if (datedEntry) {
      await removePermanentTaskEntry(assignment.worker, assignment.task, assignment.worker_name, assignment.task_name);
      return;
    }

    setSaving(true);
    setError('');
    setNotice('');
    try {
      await api.updateStaffTaskAssignment(assignment.id, { is_active: false });
      setPermanentAssignments(await api.staffTaskAssignments());
      setNotice(`${assignment.worker_name} is no longer permanently assigned to ${assignment.task_name}. Existing pay records are unchanged.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Permanent task assignment could not be removed.');
    } finally {
      setSaving(false);
    }
  }

  async function saveAssignments() {
    const duplicate = new Set<string>();
    for (const row of drafts) {
      const key = `${row.worker}:${row.task}`;
      if (duplicate.has(key)) {
        setError('A worker can only be assigned to each task once per day.');
        return;
      }
      duplicate.add(key);
      const task = tasks.find((item) => item.id === Number(row.task));
      if (task?.pay_basis === 'hourly' && (!Number.isFinite(Number(row.hours)) || Number(row.hours) <= 0)) {
        setError('Enter hours worked for each hourly task.');
        return;
      }
      if (task?.pay_basis === 'target' && (row.units_worked.trim() === '' || !Number.isInteger(Number(row.units_worked)) || Number(row.units_worked) < 0)) {
        setError('Enter the number of units completed for each target-based task.');
        return;
      }
    }
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const saved = await api.recordStaffTaskEntries(date, drafts.map((row) => ({
        worker: Number(row.worker),
        task: Number(row.task),
        hours: row.hours || '0',
        units_worked: Number(row.units_worked || 0),
      })));
      setEntries((current) => [...current.filter((entry) => entry.date !== date), ...saved]);
      await onSaved();
      setNotice('Task work and pay saved.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Task work could not be saved.');
    } finally {
      setSaving(false);
    }
  }

  return <section className="staff-task-pay-panel">
    <div className="staff-section-heading"><div><span className="staff-section-icon"><BriefcaseBusiness size={14}/></span><div><h2>Task-based pay</h2><p>Target-based tasks pay the amount for the highest target tier reached. Daily and hourly task rates apply as recorded; monthly rates count once per worker/task each month.</p></div></div></div>
    <div className="staff-task-pay-layout">
      <div>
        <form className="staff-task-form" onSubmit={(event) => void saveTask(event)}>
          <strong>{editingTaskId ? 'Edit task pay' : 'Add a task and pay'}</strong>
          <label className="catalog-field">Task name<input required maxLength={120} value={taskName} onChange={(event) => setTaskName(event.target.value)} placeholder="e.g. Packing orders"/></label>
          <label className="catalog-field">Rate basis<select value={taskBasis} onChange={(event) => {
            const basis = event.target.value as StaffTask['pay_basis'];
            setTaskBasis(basis);
            if (basis === 'target' && !taskTargetTiers.length) {
              setTaskTargetTiers([{ target_quantity: '', amount: '' }]);
            }
          }}><option value="daily">Daily</option><option value="hourly">Hourly</option><option value="monthly">Monthly</option><option value="target">Target-based</option></select></label>
          {taskBasis === 'target' ? <div className="staff-task-target-tiers">
            <strong>Target and payout tiers</strong>
            <small>The payout for the highest target reached is paid once per day; tiers do not stack.</small>
            {taskTargetTiers.map((tier, index) => <div className="staff-task-rate-fields" key={`target-tier-${index}`}>
              <label className="catalog-field">Target units<input required type="number" min="1" step="1" value={tier.target_quantity} onChange={(event) => updateTargetTier(index, { target_quantity: event.target.value })} placeholder="Units"/></label>
              <label className="catalog-field">Payout (UGX)<input required type="number" min="0.01" step="0.01" value={tier.amount} onChange={(event) => updateTargetTier(index, { amount: event.target.value })} placeholder="Amount"/></label>
              <button type="button" className="catalog-button catalog-button-light" disabled={saving} onClick={() => setTaskTargetTiers((current) => current.filter((_, tierIndex) => tierIndex !== index))}>Remove</button>
            </div>)}
            <button type="button" className="catalog-button catalog-button-light" disabled={saving} onClick={() => setTaskTargetTiers((current) => [...current, { target_quantity: '', amount: '' }])}><Plus size={13}/>Add target tier</button>
          </div> : <label className="catalog-field">Pay rate (UGX)<input required type="number" min="0.01" step="0.01" value={taskRate} onChange={(event) => setTaskRate(event.target.value)} placeholder="Enter amount"/></label>}
          <div className="staff-task-form-actions"><button className="catalog-button catalog-button-primary" disabled={saving}>{saving ? 'Saving…' : editingTaskId ? 'Update task' : 'Add task'}</button>{editingTaskId && <button type="button" className="catalog-button catalog-button-light" onClick={resetTaskForm}>Cancel</button>}</div>
        </form>
        <div className="staff-task-list"><strong>Available tasks</strong>{tasks.map((task) => <div className={`staff-task-list-row ${!task.is_active ? 'is-inactive' : ''}`} key={task.id}><span><b>{task.name}</b><small>{task.pay_basis_display} · {task.pay_basis === 'target' ? targetTierDescription(task.target_tiers) : currency(task.pay_rate)}{task.is_active ? '' : ' · Inactive'}</small></span><button type="button" className="catalog-button catalog-button-light" disabled={saving} onClick={() => editTask(task)}>Edit</button><button type="button" className="catalog-button catalog-button-light" disabled={saving} onClick={() => void setTaskActive(task, !task.is_active)}>{task.is_active ? 'Deactivate' : 'Activate'}</button></div>)}{!tasks.length && <p className="staff-history-empty">Add a task and its pay details to assign task-based pay.</p>}</div>
      </div>
      <div className="staff-task-assignments">
        <div className="staff-task-assignment-heading"><span><strong>Worker task assignments</strong><small>{new Date(`${date}T00:00:00`).toLocaleDateString('en-UG', { weekday: 'long', day: 'numeric', month: 'long' })}</small></span><button type="button" className="catalog-button catalog-button-light" onClick={addAssignment} disabled={!recordsLoaded || locked || date > today || !hasAvailableAssignment}><Plus size={13}/>Assign task</button></div>
        <div className="staff-task-earnings-summary">
          <span><small>ASSIGNED-DATE EARNINGS</small><strong>{currency(assignedDateEarnings)}</strong><small>Task earnings dated {date}; monthly rates count once</small></span>
          <span><small>{periodLabel(period)} TASK PAY</small><strong>{currency(selectedMonthTaskPay)}</strong><small>Month total used in payroll preview</small></span>
        </div>
        <div className="staff-permanent-task-panel">
          <strong>Permanent assignments</strong>
          <p>Workers with a standing assignment receive task pay for attended days from the selected date. Enter actual hours or completed target-task units when recording daily work.</p>
          <div className="staff-permanent-task-form">
            <label className="catalog-field">Worker<select value={selectedPermanentWorker} onChange={(event) => setPermanentWorker(event.target.value)}><option value="">Choose worker</option>{activeWorkers.map((worker) => <option key={worker.id} value={worker.id}>{worker.full_name}</option>)}</select></label>
            <label className="catalog-field">Task<select value={selectedPermanentTask} onChange={(event) => setPermanentTask(event.target.value)}><option value="">Choose task</option>{activeTasks.map((task) => <option key={task.id} value={task.id}>{task.name} · {task.pay_basis === 'target' ? targetTierDescription(task.target_tiers) : task.pay_basis_display}</option>)}</select></label>
            <button type="button" className="catalog-button catalog-button-light" onClick={() => void assignPermanentTask()} disabled={saving || locked || loading || !activeWorkers.length || !activeTasks.length}><Plus size={13}/>Assign</button>
          </div>
          <div className="staff-permanent-task-list">{permanentAssignments.map((assignment) => <div key={assignment.id}><span><strong>{assignment.worker_name}</strong><small>{assignment.task_name} · {assignment.pay_basis_display}{assignment.pay_basis === 'target' ? ` · ${targetTierDescription(assignment.target_tiers)}` : ` · ${currency(assignment.pay_rate)}`}</small></span><button type="button" className="catalog-icon-button" aria-label={`Delete ${assignment.task_name} assignment for ${assignment.worker_name}`} title="Delete permanent task assignment" disabled={saving || locked} onClick={() => void removePermanentAssignment(assignment)}><Trash2 size={14}/></button></div>)}{!permanentAssignments.length && <small>No permanent task assignments yet.</small>}</div>
        </div>
        {!eligibleWorkers.length && !loading && <p className="staff-history-empty">Mark a worker attended for this day before assigning additional daily tasks.</p>}
        {loading ? <p className="staff-history-empty">Loading task pay records…</p> : drafts.length ? <div className="staff-task-assignment-list">{drafts.map((row, index) => {
          const selectedTask = tasks.find((task) => task.id === Number(row.task));
          const entry = dayEntries.find((item) => item.worker === Number(row.worker) && item.task === Number(row.task));
          const permanentEntry = entry?.assignment_type === 'permanent';
          const monthlySeenEarlier = selectedTask?.pay_basis === 'monthly' && entries.some((entry) =>
            entry.date.slice(0, 7) === period && entry.date < date && entry.worker === Number(row.worker) && entry.task === Number(row.task));
          const rowBasis = entry?.pay_basis ?? selectedTask?.pay_basis;
          const rowRate = Number(entry?.pay_rate ?? selectedTask?.pay_rate ?? 0);
          const rowHours = Number(row.hours || 0);
          const rowTiers = entry?.target_tiers ?? selectedTask?.target_tiers ?? [];
          const rowPayout = Number(targetTierPayout(Number(row.units_worked), rowTiers));
          const rowAmount = rowBasis === 'daily' ? rowRate
            : rowBasis === 'hourly' ? rowRate * rowHours
              : rowBasis === 'target' ? rowPayout
                : monthlySeenEarlier ? 0 : rowRate;
          return <div className="staff-task-assignment-row" key={`${row.worker}-${row.task}-${index}`}>
            <label className="catalog-field">Worker<select disabled={locked || permanentEntry} value={row.worker} onChange={(event) => updateAssignment(index, { worker: event.target.value })}>{eligibleWorkers.map((worker) => <option key={worker.id} value={worker.id}>{worker.full_name}</option>)}</select></label>
            <label className="catalog-field">Task<select disabled={locked || permanentEntry} value={row.task} onChange={(event) => updateAssignment(index, { task: event.target.value })}>{tasks.filter((task) => task.is_active || task.id === Number(row.task)).map((task) => <option key={task.id} value={task.id} disabled={!task.is_active}>{task.name} · {task.pay_basis_display}{task.pay_basis === 'target' ? ` · ${targetTierDescription(task.target_tiers)}` : ''}</option>)}</select></label>
            {rowBasis === 'hourly' ? <label className="catalog-field">Hours<input type="number" min="0.01" step="0.25" disabled={locked} value={row.hours} onChange={(event) => updateAssignment(index, { hours: event.target.value })}/></label>
              : rowBasis === 'target' ? <label className="catalog-field">Units completed ({targetTierDescription(rowTiers)})<input type="number" min="0" step="1" required disabled={locked} value={row.units_worked} onChange={(event) => updateAssignment(index, { units_worked: event.target.value })}/></label>
                : <span className="staff-task-assignment-rate"><small>{rowBasis === 'monthly' ? `Monthly amount${monthlySeenEarlier ? ' · already counted this month' : ''}` : 'Amount for this day'}</small><strong>{currency(rowAmount)}</strong></span>}
            {rowBasis === 'hourly' && <span className="staff-task-assignment-rate"><small>Amount for these hours</small><strong>{currency(rowAmount)}</strong></span>}
            {rowBasis === 'target' && <span className="staff-task-assignment-rate"><small>{rowPayout > 0 ? 'Highest target reached · payout' : 'Target not reached'}</small><strong>{currency(rowAmount)}</strong></span>}
            <button type="button" className="catalog-icon-button" aria-label={`Delete ${permanentEntry ? 'permanent ' : ''}${entry?.task_name ?? selectedTask?.name ?? 'task'} assignment for ${entry?.worker_name ?? eligibleWorkers.find((worker) => worker.id === Number(row.worker))?.full_name ?? 'worker'}`} title={permanentEntry ? 'Delete this date’s task pay and unassign it going forward; earlier records are preserved' : 'Remove task assignment'} disabled={locked || saving} onClick={() => {
              if (permanentEntry && entry) {
                void removePermanentTaskEntry(entry.worker, entry.task, entry.worker_name, entry.task_name);
              } else if (!permanentEntry) {
                setDrafts((current) => current.filter((_, rowIndex) => rowIndex !== index));
              }
            }}><Trash2 size={14}/></button>
          </div>;
        })}</div> : <p className="staff-history-empty">No task assignments recorded for this date.</p>}
        {error && <p className="catalog-form-error">{error}</p>}
        {!recordsLoaded && !loading && error && <button type="button" className="catalog-button catalog-button-light" onClick={() => setLoadVersion((version) => version + 1)}>Retry loading task records</button>}
        {notice && <p className="staff-task-notice">{notice}</p>}
        <div className="staff-task-assignment-footer"><span>{locked ? 'Task assignments are locked after payroll is generated.' : 'Daily assignments require attended workers. Permanent task records are kept when saving.'}</span><button type="button" className="catalog-button catalog-button-primary" onClick={() => void saveAssignments()} disabled={!recordsLoaded || locked || saving || loading || date > today}>{saving ? 'Saving…' : 'Save task assignments'}</button></div>
      </div>
    </div>
  </section>;
}

function AdminLogin({ onLogin }: { onLogin: (username: string, password: string) => Promise<void> }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loginError, setLoginError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setLoginError('');
    try { await onLogin(username, password); }
    catch (cause) { setLoginError(cause instanceof Error ? cause.message : 'Administrator sign-in failed.'); }
    finally { setBusy(false); }
  }
  return <div className="access-login-wrap"><form className="access-login-panel" onSubmit={(event) => void submit(event)}><span className="access-login-icon"><BriefcaseBusiness size={22}/></span><span className="access-eyebrow">STOCKPULSE PEOPLE OPERATIONS</span><h1>Staff &amp; Payroll</h1><p>Sign in as an administrator to view compensation and manage payroll.</p><label className="catalog-field">Username<input required autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)}/></label><label className="catalog-field">Password<input type="password" required autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)}/></label>{loginError && <p className="catalog-form-error">{loginError}</p>}<button className="catalog-button catalog-button-primary access-login-button" disabled={busy}>{busy ? 'Signing in…' : 'Sign in securely'}</button></form></div>;
}

export default function StaffDashboard({ onNavigate, onSignOut }: { onNavigate: (target: DashboardTarget) => void; onSignOut: () => Promise<void> }) {
  const { confirm, dialog } = useConfirmation();
  const [dashboard, setDashboard] = useState<StaffDashboardData | null>(null);
  const [admin, setAdmin] = useState<AccessUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingRun, setSavingRun] = useState(false);
  const [showWorkerRates, setShowWorkerRates] = useState(false);
  const [period, setPeriod] = useState(savedPayrollPeriod);
  const [search, setSearch] = useState('');
  const [departmentFilter, setDepartmentFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [workerForm, setWorkerForm] = useState<StaffMember | null | undefined>(undefined);
  const [selectedWorkerId, setSelectedWorkerId] = useState<number | null>(savedPayrollWorker);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const attendancePanelRef = useRef<HTMLElement>(null);

  async function loadDashboard() {
    setLoading(true);
    setError('');
    try {
      const session = await api.accessSession();
      setAdmin(session.user);
      setDashboard(await api.staffDashboard(period));
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'The staff service could not be reached.';
      if (!/administrator sign-in required|authentication credentials/i.test(message)) {
        setError(message);
      } else setAdmin(null);
    } finally { setLoading(false); }
  }

  useEffect(() => {
    try {
      localStorage.setItem(payrollPeriodStorageKey, period);
    } catch {
      // The dashboard still works when browser storage is unavailable.
    }
    void loadDashboard();
  }, [period]);
  useEffect(() => {
    try {
      if (selectedWorkerId === null) localStorage.removeItem(payrollWorkerStorageKey);
      else localStorage.setItem(payrollWorkerStorageKey, String(selectedWorkerId));
    } catch {
      // The dashboard still works when browser storage is unavailable.
    }
  }, [selectedWorkerId]);

  async function signIn(username: string, password: string) {
    setError('');
    try {
      const result = await api.accessLogin(username, password);
      setAdmin(result.user);
      setDashboard(await api.staffDashboard(period));
    } catch (cause) {
      setAdmin(null);
      throw cause;
    }
  }

  async function signOut() {
    try { await onSignOut(); }
    finally { setAdmin(null); setDashboard(null); }
  }

  const workers = useMemo(() => (dashboard?.workers ?? []).filter((worker) => {
    const term = search.trim().toLowerCase();
    const matchesSearch = !term || `${worker.full_name} ${worker.employee_number} ${worker.job_title} ${worker.email}`.toLowerCase().includes(term);
    return matchesSearch && (departmentFilter === 'all' || worker.department === departmentFilter) && (statusFilter === 'all' || worker.status === statusFilter);
  }), [dashboard, search, departmentFilter, statusFilter]);
  const summary = dashboard?.summary;
  const currentRun = dashboard?.payroll_runs.find((run) => run.period === period) ?? null;
  const payrollTotals = currentRun ?? summary!;
  const monthlyGrossByWorker = useMemo(() => dashboard?.workers.reduce<Record<number, number>>((totals, worker) => {
    const payrollLine = currentRun?.lines.find((line) => line.worker === worker.id);
    const baseGross = (
      worker.pay_basis === 'monthly'
        ? worker.pay_rate
        : worker.pay_basis === 'hourly'
          ? Number(worker.pay_rate) * Number(worker.hours_per_period)
          : worker.period_gross
    );
    totals[worker.id] = Number(payrollLine?.gross_pay ?? (Number(baseGross) + Number(worker.period_task_pay)));
    return totals;
  }, {}) ?? {}, [dashboard, currentRun]);

  async function saveWorker(payload: StaffMemberInput) {
    if (workerForm) await api.updateStaffMember(workerForm.id, payload);
    else await api.createStaffMember(payload);
    setWorkerForm(undefined);
    await loadDashboard();
    setNotice(workerForm ? 'Worker profile updated.' : 'Worker enrolled in the staff directory.');
  }

  async function generatePayroll() {
    const confirmed = await confirm({
      title: 'Generate payroll snapshot?',
      message: `Generate a payroll snapshot for ${periodLabel(period)}? This will not initiate a bank transfer.`,
      confirmLabel: 'Generate snapshot',
    });
    if (!confirmed) return;
    setSavingRun(true);
    setError('');
    try {
      const run = await api.generatePayrollRun(period);
      await loadDashboard();
      setNotice(`${periodLabel(run.period)} payroll generated for ${run.worker_count} workers.`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Payroll could not be generated.'); }
    finally { setSavingRun(false); }
  }

  async function markPaid(run: PayrollRun) {
    const confirmed = await confirm({
      title: 'Mark payroll as paid?',
      message: `Mark the ${periodLabel(run.period)} payroll as paid? Confirm only after the transfer is completed externally.`,
      confirmLabel: 'Mark as paid',
    });
    if (!confirmed) return;
    setError('');
    try {
      await api.markPayrollPaid(run.id);
      await loadDashboard();
      setNotice(`${periodLabel(run.period)} payroll marked paid.`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Payroll status could not be updated.'); }
  }

  if (loading && !admin) return <section className="overview-state">Checking administrator session…</section>;
  if (!admin) return <AdminLogin onLogin={signIn}/>;
  if (!dashboard || !summary) return <section className="overview-state overview-error"><strong>Could not load staff and payroll</strong><span>{error}</span><button className="catalog-button catalog-button-light" onClick={() => void loadDashboard()}><RefreshCw size={14}/>Retry</button></section>;

  const paidPercentage = currentRun?.status === 'paid' ? 100 : currentRun ? 75 : 0;

  return <div className="staff-page">
    <section className="catalog-heading staff-heading"><div><div className="catalog-breadcrumb">Human Resources &amp; Compensation <span>›</span> <b>Worker Payroll &amp; Salaries</b></div><h1>Workers &amp; Monthly Payroll Management</h1><p>Manage staff records, pay details, and monthly payroll snapshots across the organization.</p></div><div className="catalog-heading-actions staff-heading-actions"><label className="catalog-select staff-period-select"><CalendarDays size={13}/><input aria-label="Payroll period" type="month" value={period} onChange={(event) => setPeriod(event.target.value)}/><ChevronDown size={12}/></label><span className={`staff-period-status ${currentRun?.status === 'paid' ? 'is-paid' : ''}`}><i/>{currentRun ? currentRun.status_display : 'Draft preview'} · {periodLabel(period)}</span><button className="catalog-button catalog-button-light" onClick={() => void loadDashboard()} disabled={loading}><RefreshCw size={13}/>Refresh</button><button className="catalog-button catalog-button-light" onClick={() => void signOut()}><LogOut size={13}/>Sign out</button></div></section>

    {error && <div className="staff-message is-error"><CircleAlert size={14}/><span>{error}</span><button onClick={() => setError('')} aria-label="Dismiss"><X size={13}/></button></div>}
    {notice && <div className="staff-message is-success"><Check size={14}/><span>{notice}</span><button onClick={() => setNotice('')} aria-label="Dismiss"><X size={13}/></button></div>}

    <section className="staff-metrics" aria-label="Payroll summary">
      <article className="staff-metric net"><div><span>MONTHLY NET PAY</span><Wallet size={15}/></div><strong>{currency(payrollTotals.net_total)}</strong><small>{currentRun ? 'Snapshot for selected pay period' : 'Draft estimate for active staff'}</small></article>
      <article className="staff-metric"><div><span>GROSS WAGES</span><Banknote size={15}/></div><strong>{currency(payrollTotals.gross_total)}</strong><small>Before configured deductions</small></article>
      <article className="staff-metric tax"><div><span>WITHHOLDING &amp; BENEFITS</span><FileText size={15}/></div><strong>{currency(Number(payrollTotals.withholding_total) + Number(payrollTotals.benefits_total))}</strong><small>{currency(payrollTotals.withholding_total)} withholding · {currency(payrollTotals.benefits_total)} benefits</small></article>
      <article className="staff-metric workforce"><div><span>ACTIVE WORKFORCE</span><Users size={15}/></div><strong>{summary.active_workers} workers</strong><small>{summary.on_leave_workers} on leave · {summary.inactive_workers} inactive</small></article>
      <article className="staff-metric disbursement"><div><span>DISBURSEMENT STATUS</span><ShieldCheck size={15}/></div><strong>{currentRun?.status === 'paid' ? 'Paid' : currentRun ? 'Ready to review' : 'Draft'}</strong><div className="staff-progress"><i style={{ width: `${paidPercentage}%` }}/></div><small>{currentRun ? `${currentRun.worker_count} worker records · ${dateLabel(currentRun.paid_at)}` : 'No payroll run for this period'}</small></article>
    </section>

    <DailyAttendancePanel key={period} period={period} workers={dashboard.workers} locked={Boolean(currentRun)} selectedWorkerId={selectedWorkerId} monthlyGrossByWorker={monthlyGrossByWorker} onSelectedWorkerChange={setSelectedWorkerId} panelRef={attendancePanelRef} onPeriodChange={setPeriod} onSaved={loadDashboard} onConfirmImport={(attendanceRows, activityRows) => confirm({ title: 'Import attendance and activities?', message: `Import ${attendanceRows} attendance and ${activityRows} activity rows for ${periodLabel(period)}? Matching rows will be updated; other records will be kept.`, confirmLabel: 'Import workbook', variant: 'danger' })}/>

    <div className="staff-main-grid">
      <section className="staff-ledger-panel">
        <div className="staff-ledger-toolbar"><label className="catalog-search"><Search size={14}/><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search name, ID, role, email"/></label><label className="catalog-select"><Filter size={12}/><select value={departmentFilter} onChange={(event) => setDepartmentFilter(event.target.value)}><option value="all">All departments</option>{dashboard.departments.map((department) => <option key={department.name} value={department.name}>{department.name}</option>)}</select><ChevronDown size={11}/></label><label className="catalog-select"><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">All statuses</option><option value="active">Active</option><option value="leave">On leave</option><option value="inactive">Inactive</option></select><ChevronDown size={11}/></label></div>
        <div className="staff-ledger-actions"><span><Users size={13}/>{workers.length} workers shown</span><button className="catalog-button catalog-button-light" onClick={() => setWorkerForm(null)}><Plus size={13}/>Add worker</button><button className="catalog-button catalog-button-primary" onClick={() => void generatePayroll()} disabled={savingRun || Boolean(currentRun)}><BriefcaseBusiness size={13}/>{savingRun ? 'Generating…' : currentRun ? 'Payroll generated' : 'Generate payroll'}</button></div>
        <div className="catalog-table-scroll staff-table-scroll"><table className="catalog-table staff-table"><thead><tr><th>NAME</th><th>ROLE</th><th>DAYS</th><th>RATE ({getCurrencyDisplay().currency}) <button type="button" className="catalog-icon-button staff-rate-visibility" aria-label={showWorkerRates ? 'Hide worker rates' : 'Show worker rates'} aria-pressed={showWorkerRates} title={showWorkerRates ? 'Hide worker rates' : 'Show worker rates'} onClick={() => setShowWorkerRates((visible) => !visible)}>{showWorkerRates ? <EyeOff size={12}/> : <Eye size={12}/>}</button></th><th>TASK PAY</th><th>PAID</th><th>UNPAID DAYS</th><th>DUE</th><th>ACTION</th></tr></thead><tbody>{workers.map((worker) => {
          const payrollLine = currentRun?.lines.find((line) => line.worker === worker.id);
          const taskPay = Number(payrollLine?.task_pay ?? worker.period_task_pay);
          const baseGross = worker.pay_basis === 'monthly' ? Number(worker.pay_rate) : worker.pay_basis === 'hourly' ? Number(worker.pay_rate) * Number(worker.hours_per_period) : Number(worker.period_gross);
          const gross = Number(payrollLine?.gross_pay ?? (baseGross + taskPay));
          const withholding = Number(payrollLine?.withholding ?? gross * Number(worker.withholding_percent) / 100);
          const benefits = Number(payrollLine?.benefits ?? (worker.pay_basis === 'daily' ? Math.min(Number(worker.benefit_deduction), gross) : worker.benefit_deduction));
          const netPay = Number(payrollLine?.net_pay ?? Math.max(0, gross - withholding - benefits));
          const paidAmount = currentRun?.status === 'paid' ? netPay : 0;
          const amountDue = currentRun?.status === 'paid' ? 0 : netPay;
          return <tr key={worker.id}>
            <td><button type="button" className={`staff-ledger-value staff-ledger-identity staff-roster-worker-link ${selectedWorkerId === worker.id ? 'is-selected' : ''}`} aria-pressed={selectedWorkerId === worker.id} onClick={() => { setSelectedWorkerId(worker.id); attendancePanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }}><strong>{worker.full_name}</strong><small>{worker.employee_number}</small></button></td>
            <td><span className="staff-ledger-value staff-ledger-identity"><strong>{worker.job_title}</strong><small>{worker.department}</small></span></td>
            <td><span className="staff-ledger-value">{worker.period_days_worked || '—'}</span></td>
            <td><span className="staff-ledger-value staff-ledger-money"><strong>{showWorkerRates ? worker.pay_basis === 'daily' ? `Weekday (15+/12+/10+/8+): ${currency(7000)} / ${currency(6000)} / ${currency(5000)} / ${currency(4000)}` : currency(worker.pay_rate) : '••••••'}</strong><small>{showWorkerRates && worker.pay_basis === 'daily' ? `Sunday (15+/12+/8+): ${currency(7000)} / ${currency(6000)} / ${currency(4000)}` : worker.pay_basis_display}</small></span></td>
            <td><span className="staff-ledger-value staff-ledger-money">{currency(taskPay)}</span></td>
            <td><span className="staff-ledger-value staff-ledger-money">{currency(paidAmount)}</span></td>
            <td><span className="staff-ledger-value" title="Scheduled and unpaid days are not tracked yet">—</span></td>
            <td><span className="staff-ledger-value staff-ledger-money staff-ledger-due">{currency(amountDue)}</span></td>
            <td><button className="catalog-button catalog-button-light staff-edit-button" onClick={() => setWorkerForm(worker)}>Edit</button></td>
          </tr>;
        })}{!workers.length && <tr><td colSpan={9} className="catalog-state">No workers match these filters. Add a worker to begin.</td></tr>}</tbody></table></div>
        <footer className="staff-table-footer"><span>Payroll amounts are stored in UGX; displayed values use {getCurrencyDisplay().currency}. Bank transfers are not initiated by this dashboard.</span><span>{dashboard.workers.length} total records</span></footer>
      </section>

      <aside className="staff-side-column">
        <section className="staff-approval-panel"><div className="staff-side-title"><span><BriefcaseBusiness size={15}/></span><div><h2>Payroll run</h2><small>{currentRun ? `Run ${currentRun.period}` : 'Selected period preview'}</small></div><i className={currentRun?.status === 'paid' ? 'paid' : ''}>{currentRun?.status_display ?? 'Draft'}</i></div>
          <div className="staff-readiness"><div className="staff-readiness-ring" style={{ '--readiness': `${paidPercentage || (summary.active_workers ? 75 : 0)}%` } as React.CSSProperties}><strong>{paidPercentage || (summary.active_workers ? 75 : 0)}%</strong></div><span><strong>{currentRun?.status === 'paid' ? 'Run complete' : currentRun ? 'Ready for review' : 'Preview calculated'}</strong><small>{summary.active_workers} active workers · {currentRun?.worker_count ?? summary.active_workers} pay entries</small></span></div>
          <ul className="staff-checklist"><li><Check size={13}/><span>Worker status and pay details included</span></li><li><Check size={13}/><span>Configured deductions validated against gross</span></li><li><Clock3 size={13}/><span>{currentRun ? `Created ${dateLabel(currentRun.created_at)}` : 'No run has been generated for this period'}</span></li></ul>
          {currentRun?.status === 'scheduled' && <button className="catalog-button catalog-button-primary staff-pay-button" onClick={() => void markPaid(currentRun)}><Check size={14}/>Mark as paid</button>}
          <p className="staff-caveat">Mark as paid only after your bank or payroll provider confirms the transfer.</p>
        </section>

        <section className="staff-enroll-panel"><div className="staff-side-title"><span><Plus size={15}/></span><div><h2>People operations</h2><small>Connected workspaces</small></div></div><button className="staff-link-row" onClick={() => onNavigate('users')}><Users size={14}/><span><strong>Users &amp; Roles</strong><small>Login accounts and permissions</small></span><ArrowRight size={14}/></button><button className="staff-link-row" onClick={() => onNavigate('expenses')}><Wallet size={14}/><span><strong>Expenses</strong><small>Operating expenses and budgets</small></span><ArrowRight size={14}/></button><button className="staff-link-row" onClick={() => onNavigate('reports')}><FileText size={14}/><span><strong>Reports</strong><small>Financial and operations reporting</small></span><ArrowRight size={14}/></button></section>

        <section className="staff-history-panel"><div className="staff-side-title"><span><Clock3 size={15}/></span><div><h2>Payroll history</h2><small>{dashboard.payroll_runs.length} recent runs</small></div></div>{dashboard.payroll_runs.length ? dashboard.payroll_runs.map((run) => <button className="staff-history-row" key={run.id} onClick={() => setPeriod(run.period)}><span><strong>{periodLabel(run.period)}</strong><small>{run.worker_count} workers · {run.status_display}</small></span><strong>{currency(run.net_total)}</strong></button>) : <p className="staff-history-empty">Payroll runs will appear here after the first monthly snapshot.</p>}</section>
      </aside>
    </div>

    {dashboard.payroll_runs.some((run) => run.period === period) && <section className="staff-payroll-details"><div className="staff-section-heading"><div><span className="staff-section-icon"><FileText size={14}/></span><div><h2>{periodLabel(period)} payroll ledger</h2><p>Per-worker amounts snapshotted at generation time.</p></div></div><span>{currentRun?.status_display ?? 'History'}</span></div><div className="catalog-table-scroll"><table className="catalog-table staff-payroll-table"><thead><tr><th>WORKER</th><th>DEPARTMENT</th><th>DAYS WORKED</th><th>TASK PAY</th><th>GROSS</th><th>WITHHOLDING</th><th>BENEFITS</th><th>NET PAY</th></tr></thead><tbody>{(currentRun?.lines ?? []).map((line) => <tr key={line.id}><td><strong>{line.worker_name}</strong><small>{line.employee_number}</small></td><td>{line.department}</td><td>{line.pay_basis === 'daily' ? line.days_worked : line.pay_basis === 'hourly' ? `${line.hours} hours` : '—'}</td><td>{currency(line.task_pay)}</td><td>{currency(line.gross_pay)}</td><td>{currency(line.withholding)}</td><td>{currency(line.benefits)}</td><td><strong>{currency(line.net_pay)}</strong></td></tr>)}</tbody></table></div></section>}

    <footer className="staff-page-footer"><span><ShieldCheck size={12}/> Compensation details are restricted to administrators.</span><span>UGX · Uganda Shilling</span></footer>
    {workerForm !== undefined && <WorkerForm worker={workerForm} onClose={() => setWorkerForm(undefined)} onSaved={saveWorker}/>}
    {dialog}
  </div>;
}
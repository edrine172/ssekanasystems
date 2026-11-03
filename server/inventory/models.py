from django.db import models
from django.utils import timezone
from uuid import uuid4


def generate_supplier_code():
    return f'SUP-{uuid4().hex[:12].upper()}'


def generate_employee_number():
    return f'EMP-{uuid4().hex[:10].upper()}'


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.name


class Supplier(models.Model):
    supplier_code = models.CharField(max_length=20, unique=True, default=generate_supplier_code)
    name = models.CharField(max_length=160)
    contact_name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    sector = models.CharField(max_length=120, blank=True)
    account_manager = models.CharField(max_length=120, blank=True)
    address = models.TextField(blank=True)
    tax_number = models.CharField(max_length=40, blank=True)
    contract_number = models.CharField(max_length=60, blank=True)
    payment_terms = models.CharField(max_length=40, default='Net 30')
    outstanding_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    lead_time_days = models.PositiveIntegerField(default=3)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Customer(models.Model):
    class Tier(models.TextChoices):
        STANDARD = 'standard', 'Standard'
        GROWTH = 'growth', 'Growth'
        ENTERPRISE = 'enterprise', 'Enterprise'

    customer_code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=180)
    contact_name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    sector = models.CharField(max_length=120, blank=True)
    tier = models.CharField(max_length=16, choices=Tier.choices, default=Tier.STANDARD)
    account_manager = models.CharField(max_length=120, blank=True)
    billing_address = models.TextField(blank=True)
    shipping_address = models.TextField(blank=True)
    tax_number = models.CharField(max_length=40, blank=True)
    tax_exempt = models.BooleanField(default=False)
    payment_terms = models.CharField(max_length=40, default='Due on receipt')
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    outstanding_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.customer_code})'


class Product(models.Model):
    sku = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=180)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, related_name='products', null=True, blank=True)
    quantity = models.PositiveIntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    location = models.CharField(max_length=120, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.sku} — {self.name}'


class Purchase(models.Model):
    class Status(models.TextChoices):
        ORDERED = 'ordered', 'Ordered'
        RECEIVED = 'received', 'Received'
        CANCELLED = 'cancelled', 'Cancelled'

    reference = models.CharField(max_length=40, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='purchases')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ORDERED)
    notes = models.CharField(max_length=240, blank=True)
    expected_delivery = models.DateField(null=True, blank=True)
    ordered_at = models.DateTimeField(auto_now_add=True)
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-ordered_at']

    def __str__(self):
        return self.reference


class SupplierLedgerEntry(models.Model):
    class EntryType(models.TextChoices):
        CHARGE = 'charge', 'Invoice'
        PAYMENT = 'payment', 'Payment'
        CREDIT = 'credit', 'Credit'

    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='ledger_entries')
    purchase = models.ForeignKey(Purchase, on_delete=models.SET_NULL, related_name='ledger_entries', null=True, blank=True)
    entry_type = models.CharField(max_length=16, choices=EntryType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=80, blank=True)
    note = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_entry_type_display()} {self.amount} for {self.supplier.supplier_code}'


class PurchaseItem(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='purchase_items')
    quantity = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['purchase', 'product'], name='unique_product_per_purchase')]

    def __str__(self):
        return f'{self.quantity} × {self.product.sku} for {self.purchase.reference}'


class BottleProduct(models.Model):
    class Category(models.TextChoices):
        UGANDA_WARAGI = 'UGANDA WARAGI', 'UGANDA WARAGI'
        GUARANTEE = 'GUARANTEE', 'GUARANTEE'

    sku = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=180)
    category = models.CharField(max_length=80, default=Category.UGANDA_WARAGI)
    unit = models.CharField(max_length=24, default='bottles')
    quantity = models.PositiveIntegerField(default=0)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    is_active = models.BooleanField(default=True)
    inventory_product = models.OneToOneField(
        Product,
        on_delete=models.PROTECT,
        related_name='bottle_catalog_entry',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['category', 'name']

    def __str__(self):
        return f'{self.sku} — {self.name}'


class BottleCustomerPO(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        PARTIAL = 'partial', 'Partially delivered'
        COMPLETED = 'completed', 'Completed'

    reference = models.CharField(max_length=40, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='bottle_purchase_orders')
    expected_delivery = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=240, blank=True)
    ordered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-ordered_at']

    def __str__(self):
        return self.reference


class BottleCustomerPOLine(models.Model):
    purchase_order = models.ForeignKey(BottleCustomerPO, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(BottleProduct, on_delete=models.PROTECT, related_name='purchase_order_lines')
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['purchase_order', 'product'], name='unique_bottle_product_per_customer_po')]

    def __str__(self):
        return f'{self.quantity} × {self.product.sku} for {self.purchase_order.reference}'


class BottleDelivery(models.Model):
    reference = models.CharField(max_length=40, unique=True)
    purchase_order = models.ForeignKey(BottleCustomerPO, on_delete=models.PROTECT, related_name='deliveries')
    notes = models.CharField(max_length=240, blank=True)
    delivered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-delivered_at']

    def __str__(self):
        return self.reference


class BottleDeliveryLine(models.Model):
    delivery = models.ForeignKey(BottleDelivery, on_delete=models.CASCADE, related_name='items')
    purchase_order_line = models.ForeignKey(BottleCustomerPOLine, on_delete=models.PROTECT, related_name='delivery_lines')
    quantity = models.PositiveIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['delivery', 'purchase_order_line'], name='unique_bottle_po_line_per_delivery')]


class ClientMaterial(models.Model):
    class MaterialType(models.TextChoices):
        SPENT_YEAST = 'spent_yeast', 'Spent Yeast'
        ASH = 'ash', 'Ash'

    material_type = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=120, blank=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    unit = models.CharField(max_length=16, default='kg')
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ['material_type']

    def __str__(self):
        return self.name or self.get_material_type_display()


class ClientMaterialPO(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        PARTIAL = 'partial', 'Partially received'
        COMPLETED = 'completed', 'Completed'

    reference = models.CharField(max_length=40, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='material_purchase_orders')
    material = models.ForeignKey(ClientMaterial, on_delete=models.PROTECT, related_name='purchase_orders')
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    expected_delivery = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=240, blank=True)
    ordered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-ordered_at']

    def __str__(self):
        return self.reference


class ClientMaterialReceipt(models.Model):
    reference = models.CharField(max_length=40, unique=True)
    purchase_order = models.ForeignKey(ClientMaterialPO, on_delete=models.PROTECT, related_name='receipts')
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    notes = models.CharField(max_length=240, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-received_at']

    def __str__(self):
        return self.reference


class Sale(models.Model):
    class PaymentMethod(models.TextChoices):
        CASH = 'cash', 'Cash'
        CARD = 'card', 'Card'
        MOBILE = 'mobile', 'Mobile'
        TRANSFER = 'transfer', 'Transfer'
        ACCOUNT = 'account', 'On account'

    receipt_number = models.CharField(max_length=40, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, related_name='sales', null=True, blank=True)
    customer_name = models.CharField(max_length=120, default='Walk-in Customer')
    payment_method = models.CharField(max_length=16, choices=PaymentMethod.choices)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default='8.50')
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    cash_tendered = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    change_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.receipt_number


class CustomerLedgerEntry(models.Model):
    class EntryType(models.TextChoices):
        CHARGE = 'charge', 'Charge'
        PAYMENT = 'payment', 'Payment'
        CREDIT = 'credit', 'Credit'

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='ledger_entries')
    sale = models.ForeignKey(Sale, on_delete=models.SET_NULL, related_name='ledger_entries', null=True, blank=True)
    entry_type = models.CharField(max_length=16, choices=EntryType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=80, blank=True)
    note = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_entry_type_display()} {self.amount} for {self.customer.customer_code}'


class SupplierInspection(models.Model):
    purchase = models.OneToOneField(Purchase, on_delete=models.CASCADE, related_name='inspection')
    accepted_units = models.PositiveIntegerField(default=0)
    rejected_units = models.PositiveIntegerField(default=0)
    inspected_by = models.CharField(max_length=120, blank=True)
    note = models.CharField(max_length=240, blank=True)
    inspected_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Inspection for {self.purchase.reference}'


class Expense(models.Model):
    class ExpenseType(models.TextChoices):
        OPERATIONAL = 'operational', 'Operational'
        FREIGHT = 'freight', 'Freight'
        CAPITAL = 'capital', 'Capital expenditure'

    class PaymentMethod(models.TextChoices):
        CARD = 'card', 'Card'
        BANK = 'bank', 'ACH / wire'
        CASH = 'cash', 'Cash'
        CHECK = 'check', 'Check'
        PETTY_CASH = 'petty_cash', 'Petty cash'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending approval'
        APPROVED = 'approved', 'Approved'
        PAID = 'paid', 'Paid'
        REJECTED = 'rejected', 'Rejected'

    expense_number = models.CharField(max_length=40, unique=True)
    merchant = models.CharField(max_length=160)
    description = models.CharField(max_length=240)
    category = models.CharField(max_length=80)
    cost_center = models.CharField(max_length=80, blank=True)
    expense_type = models.CharField(max_length=16, choices=ExpenseType.choices, default=ExpenseType.OPERATIONAL)
    amount_before_tax = models.DecimalField(max_digits=12, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=16, choices=PaymentMethod.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    reference = models.CharField(max_length=80, blank=True)
    expense_date = models.DateField(default=timezone.localdate)
    receipt_received = models.BooleanField(default=False)
    receipt_verified = models.BooleanField(default=False)
    entered_by = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-expense_date', '-created_at']

    def __str__(self):
        return f'{self.expense_number} · {self.merchant}'


class ExpenseBudget(models.Model):
    category = models.CharField(max_length=80, unique=True)
    monthly_limit = models.DecimalField(max_digits=12, decimal_places=2)
    cost_center = models.CharField(max_length=80, blank=True)
    manager = models.CharField(max_length=120, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category']

    def __str__(self):
        return f'{self.category}: {self.monthly_limit}'


class BalanceSheetAccount(models.Model):
    class Category(models.TextChoices):
        CASH_AND_CASH_EQUIVALENTS = 'cash_and_cash_equivalents', 'Cash and cash equivalents'
        CURRENT_MARKETABLE_SECURITIES = 'current_marketable_securities', 'Marketable securities'
        ACCOUNTS_RECEIVABLE_NET = 'accounts_receivable_net', 'Accounts receivable, net'
        INVENTORIES = 'inventories', 'Inventories'
        VENDOR_NON_TRADE_RECEIVABLES = 'vendor_non_trade_receivables', 'Vendor non-trade receivables'
        OTHER_CURRENT_ASSETS = 'other_current_assets', 'Other current assets'
        NONCURRENT_MARKETABLE_SECURITIES = 'noncurrent_marketable_securities', 'Marketable securities'
        PROPERTY_PLANT_EQUIPMENT_NET = 'property_plant_equipment_net', 'Property, plant and equipment, net'
        OTHER_NONCURRENT_ASSETS = 'other_noncurrent_assets', 'Other non-current assets'
        ACCOUNTS_PAYABLE = 'accounts_payable', 'Accounts payable'
        OTHER_CURRENT_LIABILITIES = 'other_current_liabilities', 'Other current liabilities'
        DEFERRED_REVENUE = 'deferred_revenue', 'Deferred revenue'
        COMMERCIAL_PAPER = 'commercial_paper', 'Commercial paper'
        CURRENT_TERM_DEBT = 'current_term_debt', 'Term debt'
        NONCURRENT_TERM_DEBT = 'noncurrent_term_debt', 'Term debt'
        OTHER_NONCURRENT_LIABILITIES = 'other_noncurrent_liabilities', 'Other non-current liabilities'
        COMMON_STOCK_AND_ADDITIONAL_PAID_IN_CAPITAL = 'common_stock_and_additional_paid_in_capital', 'Common stock and additional paid-in capital'
        RETAINED_EARNINGS = 'retained_earnings', 'Retained earnings'
        ACCUMULATED_OTHER_COMPREHENSIVE_INCOME_LOSS = 'accumulated_other_comprehensive_income_loss', 'Accumulated other comprehensive income / (loss)'

    category = models.CharField(max_length=64, choices=Category.choices, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    prior_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category']

    def __str__(self):
        return f'{self.get_category_display()}: {self.amount}'


class SecurityAuditEvent(models.Model):
    actor = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='inventory_security_events')
    action = models.CharField(max_length=80)
    target_type = models.CharField(max_length=80)
    target_id = models.CharField(max_length=80, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        permissions = [('manage_access', 'Can manage workspace access')]
        indexes = [
            models.Index(fields=['-created_at'], name='sec_audit_created_idx'),
            models.Index(fields=['target_type', '-created_at'], name='sec_audit_target_created_idx'),
        ]

    def __str__(self):
        return f'{self.action} · {self.target_type} {self.target_id}'


class SystemSetting(models.Model):
    key = models.CharField(max_length=80, unique=True)
    value = models.JSONField()
    category = models.CharField(max_length=40)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='inventory_settings_changes')

    class Meta:
        ordering = ['category', 'key']

    def __str__(self):
        return f'{self.category}.{self.key}'


class Notification(models.Model):
    class Category(models.TextChoices):
        STOCK = 'stock', 'Stock alerts'
        PROCUREMENT = 'procurement', 'Procurement'
        BILLING = 'billing', 'Billing and sales'
        OPERATIONS = 'operations', 'Operations'

    class Severity(models.TextChoices):
        INFO = 'info', 'Information'
        WARNING = 'warning', 'Warning'
        CRITICAL = 'critical', 'Critical'

    source_key = models.CharField(max_length=140, unique=True)
    category = models.CharField(max_length=16, choices=Category.choices)
    severity = models.CharField(max_length=12, choices=Severity.choices, default=Severity.INFO)
    title = models.CharField(max_length=160)
    message = models.TextField()
    target_label = models.CharField(max_length=120, blank=True)
    dashboard = models.CharField(max_length=24)
    is_read = models.BooleanField(default=False)
    is_dismissed = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class StaffMember(models.Model):
    class PayBasis(models.TextChoices):
        MONTHLY = 'monthly', 'Monthly salary'
        HOURLY = 'hourly', 'Hourly wage'
        DAILY = 'daily', 'Daily wage'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        LEAVE = 'leave', 'On leave'
        INACTIVE = 'inactive', 'Inactive'

    employee_number = models.CharField(max_length=24, unique=True, default=generate_employee_number)
    full_name = models.CharField(max_length=160)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    job_title = models.CharField(max_length=120)
    department = models.CharField(max_length=100)
    pay_basis = models.CharField(max_length=12, choices=PayBasis.choices, default=PayBasis.MONTHLY)
    pay_rate = models.DecimalField(max_digits=12, decimal_places=2)
    hours_per_period = models.DecimalField(max_digits=6, decimal_places=2, default=160)
    withholding_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    benefit_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    hire_date = models.DateField(default=timezone.localdate)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['full_name', 'employee_number']

    def __str__(self):
        return f'{self.employee_number} · {self.full_name}'


class StaffAttendance(models.Model):
    worker = models.ForeignKey(StaffMember, on_delete=models.PROTECT, related_name='attendance_records')
    date = models.DateField()
    attended = models.BooleanField(default=False)
    output_quantity = models.PositiveIntegerField(default=0)
    daily_wage_override = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    daily_wage = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    recorded_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='staff_attendance_records')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date', 'worker__full_name']
        constraints = [models.UniqueConstraint(fields=['worker', 'date'], name='unique_staff_attendance_per_day')]

    def __str__(self):
        return f'{self.worker.employee_number} · {self.date}'


class StaffTask(models.Model):
    class PayBasis(models.TextChoices):
        DAILY = 'daily', 'Daily'
        HOURLY = 'hourly', 'Hourly'
        MONTHLY = 'monthly', 'Monthly'
        TARGET = 'target', 'Target-based'

    name = models.CharField(max_length=120, unique=True)
    pay_basis = models.CharField(max_length=12, choices=PayBasis.choices)
    pay_rate = models.DecimalField(max_digits=12, decimal_places=2)
    target_tiers = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class StaffTaskAssignment(models.Model):
    worker = models.ForeignKey(StaffMember, on_delete=models.PROTECT, related_name='permanent_task_assignments')
    task = models.ForeignKey(StaffTask, on_delete=models.PROTECT, related_name='permanent_assignments')
    assigned_from = models.DateField(default=timezone.localdate)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['worker__full_name', 'task__name']
        constraints = [
            models.UniqueConstraint(
                fields=['worker', 'task'],
                condition=models.Q(is_active=True),
                name='unique_active_staff_task_assignment',
            ),
        ]

    def __str__(self):
        return f'{self.worker.employee_number} · {self.task.name}'


class StaffTaskEntry(models.Model):
    class AssignmentType(models.TextChoices):
        DAILY = 'daily', 'Daily assignment'
        PERMANENT = 'permanent', 'Permanent assignment'

    worker = models.ForeignKey(StaffMember, on_delete=models.PROTECT, related_name='task_entries')
    task = models.ForeignKey(StaffTask, on_delete=models.PROTECT, related_name='work_entries')
    date = models.DateField()
    assignment_type = models.CharField(max_length=12, choices=AssignmentType.choices, default=AssignmentType.DAILY)
    task_name = models.CharField(max_length=120)
    pay_basis = models.CharField(max_length=12, choices=StaffTask.PayBasis.choices)
    pay_rate = models.DecimalField(max_digits=12, decimal_places=2)
    hours = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    target_tiers = models.JSONField(default=list, blank=True)
    units_worked = models.PositiveIntegerField(default=0)
    recorded_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='staff_task_entries')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date', 'worker__full_name', 'task_name']
        constraints = [
            models.UniqueConstraint(fields=['worker', 'task', 'date'], name='unique_staff_task_per_worker_day'),
        ]
        indexes = [
            models.Index(fields=['date', 'worker'], name='staff_task_date_worker_idx'),
        ]

    def __str__(self):
        return f'{self.worker.employee_number} · {self.task_name} · {self.date}'


class PayrollRun(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = 'scheduled', 'Scheduled'
        PAID = 'paid', 'Paid'

    period = models.CharField(max_length=7)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED)
    worker_count = models.PositiveIntegerField(default=0)
    gross_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    withholding_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    benefits_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='inventory_payroll_runs')
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-period', '-created_at']
        constraints = [models.UniqueConstraint(fields=['period'], name='unique_payroll_run_per_period')]

    def __str__(self):
        return f'Payroll {self.period}'


class PayrollLine(models.Model):
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name='lines')
    worker = models.ForeignKey(StaffMember, on_delete=models.PROTECT, related_name='payroll_lines')
    employee_number = models.CharField(max_length=24)
    worker_name = models.CharField(max_length=160)
    job_title = models.CharField(max_length=120)
    department = models.CharField(max_length=100)
    pay_basis = models.CharField(max_length=12, choices=StaffMember.PayBasis.choices)
    hours = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    days_worked = models.PositiveIntegerField(default=0)
    task_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gross_pay = models.DecimalField(max_digits=12, decimal_places=2)
    withholding = models.DecimalField(max_digits=12, decimal_places=2)
    benefits = models.DecimalField(max_digits=12, decimal_places=2)
    net_pay = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ['worker_name', 'employee_number']
        constraints = [models.UniqueConstraint(fields=['run', 'worker'], name='unique_worker_per_payroll_run')]

    def __str__(self):
        return f'{self.employee_number} · {self.run.period}'


class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='sale_items')
    product_name = models.CharField(max_length=180)
    product_sku = models.CharField(max_length=64)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f'{self.quantity} × {self.product_sku} on {self.sale.receipt_number}'


class StockMovement(models.Model):
    class MovementType(models.TextChoices):
        INBOUND = 'inbound', 'Inbound'
        OUTBOUND = 'outbound', 'Outbound'
        ADJUSTMENT = 'adjustment', 'Adjustment'
        RETURN = 'return', 'Return'

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='movements')
    movement_type = models.CharField(max_length=16, choices=MovementType.choices)
    quantity = models.IntegerField()
    note = models.CharField(max_length=240, blank=True)
    reference = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_movement_type_display()} {self.quantity} × {self.product.sku}'

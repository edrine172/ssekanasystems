from django.db import models
from django.utils import timezone
from .catalog_models import Category


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
    expense_type = models.CharField(max_length=80, default=ExpenseType.OPERATIONAL)
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


class ExpenseCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class ExpenseTypeOption(models.Model):
    value = models.SlugField(max_length=80, unique=True)
    label = models.CharField(max_length=80, unique=True)

    class Meta:
        ordering = ['label']

    def __str__(self):
        return self.label


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

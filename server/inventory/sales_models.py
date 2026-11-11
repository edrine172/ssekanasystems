from django.db import models
from .catalog_models import Product


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

    class PaymentMethod(models.TextChoices):
        CASH = 'cash', 'Cash'
        CARD = 'card', 'Card'
        MOBILE = 'mobile', 'Mobile'
        TRANSFER = 'transfer', 'Bank transfer'
        CHECK = 'check', 'Check'

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='ledger_entries')
    sale = models.ForeignKey(Sale, on_delete=models.SET_NULL, related_name='ledger_entries', null=True, blank=True)
    entry_type = models.CharField(max_length=16, choices=EntryType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=16, choices=PaymentMethod.choices, blank=True, default='')
    reference = models.CharField(max_length=80, blank=True)
    note = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_entry_type_display()} {self.amount} for {self.customer.customer_code}'


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

from django.db import models
from uuid import uuid4


def generate_supplier_code():
    return f'SUP-{uuid4().hex[:12].upper()}'


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

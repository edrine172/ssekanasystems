from django.db import models
from .catalog_models import Category, Product, Supplier
from .sales_models import Customer


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
        indexes = [
            models.Index(fields=['supplier', '-ordered_at'], name='purchase_supplier_date_idx'),
            models.Index(fields=['status', 'expected_delivery'], name='purchase_status_due_idx'),
        ]

    def __str__(self):
        return self.reference


class SupplierLedgerEntry(models.Model):
    class EntryType(models.TextChoices):
        CHARGE = 'charge', 'Invoice'
        PAYMENT = 'payment', 'Payment'
        CREDIT = 'credit', 'Credit'

    class PaymentMethod(models.TextChoices):
        CASH = 'cash', 'Cash'
        CARD = 'card', 'Card'
        MOBILE = 'mobile', 'Mobile'
        TRANSFER = 'transfer', 'Bank transfer'
        CHECK = 'check', 'Check'

    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='ledger_entries')
    purchase = models.ForeignKey(Purchase, on_delete=models.SET_NULL, related_name='ledger_entries', null=True, blank=True)
    entry_type = models.CharField(max_length=16, choices=EntryType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=16, choices=PaymentMethod.choices, blank=True, default='')
    reference = models.CharField(max_length=80, blank=True)
    note = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['supplier', '-created_at'], name='supp_ledger_created_idx'),
            models.Index(fields=['purchase', 'entry_type'], name='supp_ledger_purchase_type_idx'),
        ]

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


class SupplierInspection(models.Model):
    purchase = models.OneToOneField(Purchase, on_delete=models.CASCADE, related_name='inspection')
    accepted_units = models.PositiveIntegerField(default=0)
    rejected_units = models.PositiveIntegerField(default=0)
    inspected_by = models.CharField(max_length=120, blank=True)
    note = models.CharField(max_length=240, blank=True)
    inspected_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Inspection for {self.purchase.reference}'

from decimal import Decimal
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers
from .models import BalanceSheetAccount, BottleCustomerPO, BottleCustomerPOLine, BottleDelivery, BottleDeliveryLine, BottleProduct, Category, ClientMaterial, ClientMaterialPO, ClientMaterialReceipt, Customer, CustomerLedgerEntry, Expense, ExpenseBudget, Notification, PayrollLine, PayrollRun, Product, Purchase, PurchaseItem, Sale, SaleItem, StaffAttendance, StaffMember, StaffTask, StaffTaskAssignment, StaffTaskEntry, StockMovement, Supplier, SupplierLedgerEntry


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'description', 'created_at']
        read_only_fields = ['id', 'created_at']


class SupplierSerializer(serializers.ModelSerializer):
    lifetime_spend = serializers.SerializerMethodField()
    completed_orders = serializers.SerializerMethodField()
    on_time_delivery_rate = serializers.SerializerMethodField()

    def _received_orders(self, supplier):
        return [purchase for purchase in supplier.purchases.all() if purchase.status == Purchase.Status.RECEIVED]

    def get_lifetime_spend(self, supplier):
        total = sum(
            (item.quantity * item.unit_cost for purchase in self._received_orders(supplier) for item in purchase.items.all()),
            Decimal('0'),
        )
        return str(total.quantize(Decimal('0.01')))

    def get_completed_orders(self, supplier):
        return len(self._received_orders(supplier))

    def get_on_time_delivery_rate(self, supplier):
        rated = [purchase for purchase in self._received_orders(supplier) if purchase.expected_delivery]
        if not rated:
            return None
        on_time = sum(1 for purchase in rated if purchase.received_at and purchase.received_at.date() <= purchase.expected_delivery)
        return round(on_time * 100 / len(rated), 1)

    class Meta:
        model = Supplier
        fields = [
            'id', 'supplier_code', 'name', 'contact_name', 'email', 'phone', 'sector',
            'account_manager', 'address', 'tax_number', 'contract_number', 'payment_terms',
            'outstanding_balance', 'is_active', 'lead_time_days', 'lifetime_spend',
            'completed_orders', 'on_time_delivery_rate', 'created_at',
        ]
        read_only_fields = ['id', 'supplier_code', 'outstanding_balance', 'lifetime_spend', 'completed_orders', 'on_time_delivery_rate', 'created_at']

    def create(self, validated_data):
        return Supplier.objects.create(**validated_data)


class CustomerSerializer(serializers.ModelSerializer):
    tax_exempt = serializers.SerializerMethodField()
    lifetime_revenue = serializers.SerializerMethodField()
    completed_orders = serializers.SerializerMethodField()

    def get_tax_exempt(self, customer):
        return False

    def get_lifetime_revenue(self, customer):
        from django.db.models import Sum
        total = customer.sales.aggregate(total=Sum('total'))['total'] or Decimal('0')
        return str(total.quantize(Decimal('0.01')))

    def get_completed_orders(self, customer):
        return customer.sales.count()

    def create(self, validated_data):
        from uuid import uuid4
        validated_data['customer_code'] = f'CUST-{uuid4().hex[:6].upper()}'
        return super().create(validated_data)

    class Meta:
        model = Customer
        fields = [
            'id', 'customer_code', 'name', 'contact_name', 'email', 'phone', 'sector', 'tier',
            'account_manager', 'billing_address', 'shipping_address', 'tax_number', 'tax_exempt',
            'payment_terms', 'credit_limit', 'outstanding_balance', 'is_active', 'lifetime_revenue',
            'completed_orders', 'created_at',
        ]
        read_only_fields = ['id', 'customer_code', 'tax_exempt', 'outstanding_balance', 'lifetime_revenue', 'completed_orders', 'created_at']


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    supplier_name = serializers.CharField(source='supplier.name', read_only=True, default='')

    class Meta:
        model = Product
        fields = ['id', 'sku', 'name', 'category', 'category_name', 'supplier', 'supplier_name', 'quantity', 'reorder_level', 'is_active', 'unit_price', 'cost_price', 'location', 'updated_at', 'created_at']
        read_only_fields = ['id', 'updated_at', 'created_at']


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'category', 'severity', 'title', 'message', 'target_label', 'dashboard', 'is_read', 'created_at']
        read_only_fields = fields


class StockMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_sku = serializers.CharField(source='product.sku', read_only=True)
    supplier_name = serializers.CharField(source='product.supplier.name', read_only=True, default='')
    amount = serializers.SerializerMethodField()

    def get_amount(self, movement):
        price = movement.product.cost_price if movement.movement_type == 'inbound' else movement.product.unit_price
        return str(abs(movement.quantity) * price)

    def validate(self, attrs):
        movement_type = attrs.get('movement_type', getattr(self.instance, 'movement_type', None))
        quantity = attrs.get('quantity', getattr(self.instance, 'quantity', 0))
        if movement_type != 'adjustment' and quantity <= 0:
            raise serializers.ValidationError({'quantity': 'Inbound, outbound, and return quantities must be greater than zero.'})
        if movement_type == 'adjustment' and quantity == 0:
            raise serializers.ValidationError({'quantity': 'An adjustment must change stock by a non-zero amount.'})
        return attrs

    class Meta:
        model = StockMovement
        fields = ['id', 'product', 'product_name', 'product_sku', 'supplier_name', 'movement_type', 'quantity', 'amount', 'note', 'reference', 'created_at']
        read_only_fields = ['id', 'created_at']


class StockAdjustmentSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    adjustment_type = serializers.ChoiceField(choices=['increase', 'decrease', 'damage', 'loss', 'count'])
    quantity = serializers.IntegerField(required=False, min_value=1)
    counted_quantity = serializers.IntegerField(required=False, min_value=0)
    reason = serializers.CharField(max_length=80)
    reference = serializers.CharField(max_length=80, required=False, allow_blank=True)
    notes = serializers.CharField(max_length=158, required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs['adjustment_type'] == 'count' and 'counted_quantity' not in attrs:
            raise serializers.ValidationError({'counted_quantity': 'Enter the quantity found during the stock count.'})
        if attrs['adjustment_type'] != 'count' and 'quantity' not in attrs:
            raise serializers.ValidationError({'quantity': 'Enter the number of units to adjust.'})
        return attrs


class PurchaseItemSerializer(serializers.ModelSerializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_sku = serializers.CharField(source='product.sku', read_only=True)
    line_total = serializers.SerializerMethodField()

    def get_line_total(self, item):
        return str(item.quantity * item.unit_cost)

    class Meta:
        model = PurchaseItem
        fields = ['id', 'product', 'product_name', 'product_sku', 'quantity', 'unit_cost', 'line_total']
        read_only_fields = ['id']


class PurchaseSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)
    items = PurchaseItemSerializer(many=True)
    item_count = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    paid_amount = serializers.SerializerMethodField()
    remaining_balance = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()

    def get_item_count(self, purchase):
        return sum(item.quantity for item in purchase.items.all())

    def get_total(self, purchase):
        return str(sum((item.quantity * item.unit_cost for item in purchase.items.all()), start=0))

    def get_paid_amount(self, purchase):
        return str(sum(
            (entry.amount for entry in purchase.ledger_entries.all()
             if entry.entry_type == SupplierLedgerEntry.EntryType.PAYMENT),
            start=Decimal('0'),
        ).quantize(Decimal('0.01')))

    def get_remaining_balance(self, purchase):
        total = sum((item.quantity * item.unit_cost for item in purchase.items.all()), start=Decimal('0'))
        paid = sum(
            (entry.amount for entry in purchase.ledger_entries.all()
             if entry.entry_type == SupplierLedgerEntry.EntryType.PAYMENT),
            start=Decimal('0'),
        )
        return str(max(total - paid, Decimal('0')).quantize(Decimal('0.01')))

    def get_payment_status(self, purchase):
        if purchase.status != Purchase.Status.RECEIVED:
            return 'not_due'
        return 'paid' if Decimal(self.get_remaining_balance(purchase)) == 0 else (
            'partial' if Decimal(self.get_paid_amount(purchase)) > 0 else 'unpaid'
        )

    def validate_items(self, items):
        product_ids = [item['product'].id for item in items]
        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError('Each product can appear only once per purchase order.')
        return items

    def create(self, validated_data):
        from uuid import uuid4
        items = validated_data.pop('items')
        validated_data['reference'] = f"PO-{timezone.now().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"
        purchase = Purchase.objects.create(**validated_data)
        PurchaseItem.objects.bulk_create([
            PurchaseItem(purchase=purchase, **item) for item in items
        ])
        return purchase

    class Meta:
        model = Purchase
        fields = ['id', 'reference', 'supplier', 'supplier_name', 'status', 'items', 'item_count', 'total', 'paid_amount', 'remaining_balance', 'payment_status', 'notes', 'expected_delivery', 'ordered_at', 'received_at']
        read_only_fields = ['id', 'reference', 'status', 'ordered_at', 'received_at']


class BottleProductSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source='inventory_product_id', read_only=True)
    inventory_product = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.filter(is_active=True),
        required=False,
        write_only=True,
    )
    sku = serializers.CharField(required=False)
    name = serializers.CharField(required=False)
    quantity = serializers.IntegerField(required=False, min_value=0)

    def validate_unit_price(self, value):
        if value < 0:
            raise serializers.ValidationError('Bottle price cannot be negative.')
        return value

    def validate(self, attrs):
        inventory_product = attrs.get('inventory_product')
        if inventory_product and BottleProduct.objects.filter(inventory_product=inventory_product).exists():
            raise serializers.ValidationError({
                'inventory_product': 'This product is already linked to the delivery catalog.',
            })
        if inventory_product is None:
            sku = attrs.get('sku')
            if not sku or not attrs.get('name'):
                raise serializers.ValidationError('Choose a product or provide its SKU and name.')
            existing_product = Product.objects.filter(sku=sku).first()
            if existing_product and not existing_product.is_active:
                raise serializers.ValidationError({'sku': 'This product is inactive in the product dashboard.'})
            if existing_product and BottleProduct.objects.filter(inventory_product=existing_product).exists():
                raise serializers.ValidationError({'sku': 'This product is already linked to the delivery catalog.'})
        return attrs

    def create(self, validated_data):
        inventory_product = validated_data.pop('inventory_product', None)
        if inventory_product is None:
            sku = validated_data.pop('sku')
            name = validated_data.pop('name')
            quantity = validated_data.pop('quantity')
            category_name = validated_data['category'][:100] or 'Uncategorized'
            category, _ = Category.objects.get_or_create(name=category_name)
            inventory_product = Product.objects.filter(sku=sku).first()
            if inventory_product is None:
                inventory_product = Product.objects.create(
                    sku=sku,
                    name=name,
                    category=category,
                    quantity=quantity,
                    unit_price=validated_data['unit_price'],
                    cost_price=0,
                )
            validated_data['sku'] = inventory_product.sku
            validated_data['name'] = inventory_product.name
            validated_data['quantity'] = inventory_product.quantity
            validated_data['inventory_product'] = inventory_product
        else:
            validated_data['sku'] = inventory_product.sku
            validated_data['name'] = inventory_product.name
            validated_data['quantity'] = inventory_product.quantity
            validated_data['inventory_product'] = inventory_product
        bottle_product = super().create(validated_data)
        if inventory_product is not None:
            bottle_product.quantity = inventory_product.quantity
            bottle_product.save(update_fields=['quantity'])
        return bottle_product

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data.update({
            'id': instance.inventory_product_id,
            'sku': instance.inventory_product.sku,
            'name': instance.inventory_product.name,
            'quantity': instance.inventory_product.quantity,
        })
        return data

    class Meta:
        model = BottleProduct
        fields = ['id', 'inventory_product', 'sku', 'name', 'category', 'unit', 'quantity', 'unit_price', 'is_active', 'created_at']
        read_only_fields = ['id', 'created_at']


class BottleInventoryProductField(serializers.RelatedField):
    def to_internal_value(self, data):
        try:
            inventory_product = Product.objects.get(pk=data, is_active=True)
        except (Product.DoesNotExist, TypeError, ValueError):
            raise serializers.ValidationError('Select an active product from the product dashboard.')
        try:
            return BottleProduct.objects.get(inventory_product=inventory_product, is_active=True)
        except BottleProduct.DoesNotExist:
            raise serializers.ValidationError('This product is not available in the delivery catalog.')

    def to_representation(self, value):
        return value.inventory_product_id


class BottleCustomerPOLineSerializer(serializers.ModelSerializer):
    product = BottleInventoryProductField(queryset=Product.objects.filter(is_active=True))
    product_name = serializers.CharField(source='product.inventory_product.name', read_only=True)
    product_sku = serializers.CharField(source='product.inventory_product.sku', read_only=True)
    category = serializers.CharField(source='product.category', read_only=True)
    unit = serializers.CharField(source='product.unit', read_only=True)
    quantity = serializers.IntegerField(min_value=1)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'))
    delivered_quantity = serializers.SerializerMethodField()
    remaining_quantity = serializers.SerializerMethodField()
    line_total = serializers.SerializerMethodField()

    def get_delivered_quantity(self, item):
        return sum(row.quantity for row in item.delivery_lines.all())

    def get_remaining_quantity(self, item):
        return max(item.quantity - self.get_delivered_quantity(item), 0)

    def get_line_total(self, item):
        return str((item.quantity * item.unit_price).quantize(Decimal('0.01')))

    class Meta:
        model = BottleCustomerPOLine
        fields = ['id', 'product', 'product_name', 'product_sku', 'category', 'unit', 'quantity', 'unit_price', 'line_total', 'delivered_quantity', 'remaining_quantity']
        read_only_fields = ['id']


class BottleDeliveryRecordLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='purchase_order_line.product.inventory_product.name', read_only=True)
    product_sku = serializers.CharField(source='purchase_order_line.product.inventory_product.sku', read_only=True)
    unit = serializers.CharField(source='purchase_order_line.product.unit', read_only=True)

    class Meta:
        model = BottleDeliveryLine
        fields = ['id', 'purchase_order_line', 'product_name', 'product_sku', 'unit', 'quantity']
        read_only_fields = fields


class BottleDeliveryRecordSerializer(serializers.ModelSerializer):
    items = BottleDeliveryRecordLineSerializer(many=True, read_only=True)

    class Meta:
        model = BottleDelivery
        fields = ['id', 'reference', 'notes', 'delivered_at', 'items']
        read_only_fields = fields


class BottleCustomerPOSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    items = BottleCustomerPOLineSerializer(many=True, allow_empty=False)
    deliveries = BottleDeliveryRecordSerializer(many=True, read_only=True)
    total = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    def get_total(self, purchase_order):
        total = sum((item.quantity * item.unit_price for item in purchase_order.items.all()), Decimal('0'))
        return str(total.quantize(Decimal('0.01')))

    def get_status(self, purchase_order):
        lines = list(purchase_order.items.all())
        if lines and all(
            sum(row.quantity for row in item.delivery_lines.all()) >= item.quantity
            for item in lines
        ):
            return BottleCustomerPO.Status.COMPLETED
        if any(row.quantity for item in lines for row in item.delivery_lines.all()):
            return BottleCustomerPO.Status.PARTIAL
        return BottleCustomerPO.Status.OPEN

    def validate_items(self, items):
        product_ids = [item['product'].id for item in items]
        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError('Each bottle catalog item can appear only once per PO.')
        if any(not item['product'].is_active for item in items):
            raise serializers.ValidationError('Inactive bottle catalog items cannot be ordered.')
        return items

    def create(self, validated_data):
        from uuid import uuid4
        items = validated_data.pop('items')
        if not validated_data.get('reference'):
            validated_data['reference'] = f"CBPO-{timezone.now().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"
        purchase_order = BottleCustomerPO.objects.create(**validated_data)
        BottleCustomerPOLine.objects.bulk_create([
            BottleCustomerPOLine(purchase_order=purchase_order, **item) for item in items
        ])
        return purchase_order

    class Meta:
        model = BottleCustomerPO
        fields = ['id', 'reference', 'customer', 'customer_name', 'items', 'deliveries', 'total', 'status', 'expected_delivery', 'notes', 'ordered_at']
        read_only_fields = ['id', 'status', 'ordered_at']
        extra_kwargs = {'reference': {'required': False}}


class BottleDeliveryLineInputSerializer(serializers.Serializer):
    purchase_order_line = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)


class BottleDeliverySerializer(serializers.Serializer):
    items = BottleDeliveryLineInputSerializer(many=True, allow_empty=False)
    notes = serializers.CharField(max_length=240, required=False, allow_blank=True)

    def validate_items(self, items):
        line_ids = [item['purchase_order_line'] for item in items]
        if len(line_ids) != len(set(line_ids)):
            raise serializers.ValidationError('Each PO line can only be included once per delivery.')
        return items


class ClientMaterialSerializer(serializers.ModelSerializer):
    material_type = serializers.CharField(read_only=True)
    name = serializers.CharField(max_length=120)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'))

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError('Enter a product name.')
        return name

    def create(self, validated_data):
        key = slugify(validated_data['name'])[:64]
        if not key:
            raise serializers.ValidationError({'name': 'The product name must contain letters or numbers.'})
        if ClientMaterial.objects.filter(material_type=key).exists():
            raise serializers.ValidationError({'name': 'A client-supplied product with this name already exists.'})
        validated_data['material_type'] = key
        return super().create(validated_data)

    class Meta:
        model = ClientMaterial
        fields = ['id', 'material_type', 'name', 'quantity', 'unit', 'unit_price']
        read_only_fields = ['id', 'material_type', 'quantity']
        extra_kwargs = {
            'unit': {'required': True},
            'unit_price': {'required': True},
        }


class ClientMaterialReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientMaterialReceipt
        fields = ['id', 'reference', 'quantity', 'notes', 'received_at']
        read_only_fields = ['id', 'received_at']


class ClientMaterialPOSerializer(serializers.ModelSerializer):
    quantity = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'))
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    material_name = serializers.CharField(source='material.name', read_only=True)
    material_unit = serializers.CharField(source='material.unit', read_only=True)
    receipts = ClientMaterialReceiptSerializer(many=True, read_only=True)
    received_quantity = serializers.SerializerMethodField()
    remaining_quantity = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    def get_received_quantity(self, purchase_order):
        return sum((receipt.quantity for receipt in purchase_order.receipts.all()), Decimal('0'))

    def get_remaining_quantity(self, purchase_order):
        return max(purchase_order.quantity - self.get_received_quantity(purchase_order), Decimal('0'))

    def get_total(self, purchase_order):
        return str((purchase_order.quantity * purchase_order.unit_price).quantize(Decimal('0.01')))

    def get_status(self, purchase_order):
        received = self.get_received_quantity(purchase_order)
        if received >= purchase_order.quantity:
            return ClientMaterialPO.Status.COMPLETED
        return ClientMaterialPO.Status.PARTIAL if received > 0 else ClientMaterialPO.Status.OPEN

    class Meta:
        model = ClientMaterialPO
        fields = ['id', 'reference', 'customer', 'customer_name', 'material', 'material_name', 'material_unit', 'quantity', 'unit_price', 'total', 'received_quantity', 'remaining_quantity', 'status', 'expected_delivery', 'notes', 'ordered_at', 'receipts']
        read_only_fields = ['id', 'status', 'ordered_at']
        extra_kwargs = {'reference': {'required': False}}


class ClientMaterialReceiptInputSerializer(serializers.Serializer):
    quantity = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    notes = serializers.CharField(max_length=240, required=False, allow_blank=True)


class SaleItemSerializer(serializers.ModelSerializer):
    line_total = serializers.SerializerMethodField()

    def get_line_total(self, item):
        return str(item.quantity * item.unit_price)

    class Meta:
        model = SaleItem
        fields = ['id', 'product', 'product_name', 'product_sku', 'quantity', 'unit_price', 'unit_cost', 'line_total']
        read_only_fields = fields


class SaleSerializer(serializers.ModelSerializer):
    items = SaleItemSerializer(many=True, read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    customer = serializers.PrimaryKeyRelatedField(read_only=True)
    paid_amount = serializers.SerializerMethodField()
    remaining_balance = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()

    def has_account_balance(self, sale):
        return sale.payment_method == Sale.PaymentMethod.ACCOUNT or any(
            entry.entry_type == CustomerLedgerEntry.EntryType.CHARGE
            for entry in sale.ledger_entries.all()
        )

    def get_paid_amount(self, sale):
        if not self.has_account_balance(sale):
            return str(sale.total.quantize(Decimal('0.01')))
        paid_amounts = self.context.get('sale_paid_amounts')
        paid = paid_amounts.get(sale.id, Decimal('0')) if paid_amounts is not None else sum(
            (entry.amount for entry in sale.ledger_entries.all()
             if entry.entry_type == CustomerLedgerEntry.EntryType.PAYMENT),
            Decimal('0'),
        )
        return str(paid.quantize(Decimal('0.01')))

    def get_remaining_balance(self, sale):
        if not self.has_account_balance(sale):
            return '0.00'
        return str(max(sale.total - Decimal(self.get_paid_amount(sale)), Decimal('0')).quantize(Decimal('0.01')))

    def get_payment_status(self, sale):
        remaining_balance = Decimal(self.get_remaining_balance(sale))
        if remaining_balance == 0:
            return 'paid'
        return 'partial' if Decimal(self.get_paid_amount(sale)) > 0 else 'unpaid'

    class Meta:
        model = Sale
        fields = [
            'id', 'receipt_number', 'customer', 'customer_name', 'payment_method', 'payment_method_display',
            'subtotal', 'discount_percent', 'discount_amount', 'tax_rate', 'tax_amount', 'total',
            'cash_tendered', 'change_due', 'paid_amount', 'remaining_balance', 'payment_status', 'items', 'created_at',
        ]
        read_only_fields = fields


class SaleCheckoutItemSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))
    quantity = serializers.IntegerField(min_value=1)
    unit_price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0'),
        required=False,
    )


class SaleCheckoutSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all(), required=False, allow_null=True)
    customer_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    payment_method = serializers.ChoiceField(choices=Sale.PaymentMethod.choices)
    discount_percent = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100, default=0)
    cash_tendered = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False, allow_null=True)
    items = SaleCheckoutItemSerializer(many=True, allow_empty=False)

    def validate_items(self, items):
        product_ids = [item['product'].id for item in items]
        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError('Each product can appear only once in the cart.')
        return items

    def validate(self, attrs):
        customer = attrs.get('customer')
        if customer is not None and not customer.is_active:
            raise serializers.ValidationError({'customer': 'This customer account is inactive.'})
        if attrs['payment_method'] == Sale.PaymentMethod.ACCOUNT:
            if customer is None:
                raise serializers.ValidationError({'customer': 'Select a customer for an on-account sale.'})
        return attrs


class CustomerLedgerEntrySerializer(serializers.ModelSerializer):
    sale_reference = serializers.CharField(source='sale.receipt_number', read_only=True, default='')
    entry_type_display = serializers.CharField(source='get_entry_type_display', read_only=True)

    class Meta:
        model = CustomerLedgerEntry
        fields = ['id', 'entry_type', 'entry_type_display', 'amount', 'reference', 'note', 'sale_reference', 'created_at']


class CustomerPaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    reference = serializers.CharField(max_length=80, required=False, allow_blank=True)
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)
    sale = serializers.PrimaryKeyRelatedField(queryset=Sale.objects.all(), required=False)


class SupplierLedgerEntrySerializer(serializers.ModelSerializer):
    purchase_reference = serializers.CharField(source='purchase.reference', read_only=True, default='')
    entry_type_display = serializers.CharField(source='get_entry_type_display', read_only=True)

    class Meta:
        model = SupplierLedgerEntry
        fields = ['id', 'entry_type', 'entry_type_display', 'amount', 'reference', 'note', 'purchase_reference', 'created_at']


class SupplierPaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    reference = serializers.CharField(max_length=80, required=False, allow_blank=True)
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)


class ExpenseSerializer(serializers.ModelSerializer):
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    amount_before_tax = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'))
    tax_amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'), required=False, default=Decimal('0'))

    def validate(self, attrs):
        amount_before_tax = attrs.get('amount_before_tax', getattr(self.instance, 'amount_before_tax', Decimal('0')))
        tax_amount = attrs.get('tax_amount', getattr(self.instance, 'tax_amount', Decimal('0')))
        if amount_before_tax + tax_amount <= 0:
            raise serializers.ValidationError({'amount_before_tax': 'Expense total must be greater than zero.'})
        receipt_received = attrs.get('receipt_received', getattr(self.instance, 'receipt_received', False))
        receipt_verified = attrs.get('receipt_verified', getattr(self.instance, 'receipt_verified', False))
        if receipt_verified and not receipt_received:
            raise serializers.ValidationError({'receipt_verified': 'A receipt must be received before it can be verified.'})
        return attrs

    def create(self, validated_data):
        from uuid import uuid4
        validated_data['expense_number'] = f"EXP-{timezone.now().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"
        validated_data['total_amount'] = validated_data['amount_before_tax'] + validated_data.get('tax_amount', Decimal('0'))
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if 'amount_before_tax' in validated_data or 'tax_amount' in validated_data:
            before_tax = validated_data.get('amount_before_tax', instance.amount_before_tax)
            tax = validated_data.get('tax_amount', instance.tax_amount)
            validated_data['total_amount'] = before_tax + tax
        return super().update(instance, validated_data)

    class Meta:
        model = Expense
        fields = [
            'id', 'expense_number', 'merchant', 'description', 'category', 'cost_center', 'expense_type',
            'amount_before_tax', 'tax_amount', 'total_amount', 'payment_method', 'payment_method_display',
            'status', 'status_display', 'reference', 'expense_date', 'receipt_received', 'receipt_verified',
            'entered_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'expense_number', 'total_amount', 'created_at', 'updated_at']


class ExpenseBudgetSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseBudget
        fields = ['id', 'category', 'monthly_limit', 'cost_center', 'manager', 'updated_at']
        read_only_fields = ['id', 'updated_at']


class BalanceSheetAccountSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    prior_amount = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)

    class Meta:
        model = BalanceSheetAccount
        fields = ['id', 'category', 'amount', 'prior_amount', 'updated_at']
        read_only_fields = ['id', 'category', 'updated_at']


class StaffMemberSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    pay_basis_display = serializers.CharField(source='get_pay_basis_display', read_only=True)
    period_days_worked = serializers.SerializerMethodField()
    period_gross = serializers.SerializerMethodField()
    period_task_pay = serializers.SerializerMethodField()

    def get_period_days_worked(self, worker):
        return self.context.get('attendance_totals', {}).get(worker.id, {}).get('days_worked', 0)

    def get_period_gross(self, worker):
        totals = self.context.get('attendance_totals', {}).get(worker.id, {})
        return totals.get('gross', Decimal('0.00'))

    def get_period_task_pay(self, worker):
        return self.context.get('task_pay_totals', {}).get(worker.id, Decimal('0.00'))

    def validate(self, attrs):
        pay_basis = attrs.get('pay_basis', getattr(self.instance, 'pay_basis', StaffMember.PayBasis.MONTHLY))
        pay_rate = attrs.get('pay_rate', getattr(self.instance, 'pay_rate', Decimal('0')))
        hours = attrs.get('hours_per_period', getattr(self.instance, 'hours_per_period', Decimal('160')))
        withholding_percent = attrs.get('withholding_percent', getattr(self.instance, 'withholding_percent', Decimal('0')))
        benefits = attrs.get('benefit_deduction', getattr(self.instance, 'benefit_deduction', Decimal('0')))
        gross = pay_rate if pay_basis in (StaffMember.PayBasis.MONTHLY, StaffMember.PayBasis.DAILY) else pay_rate * hours
        if pay_rate <= 0:
            raise serializers.ValidationError({'pay_rate': 'Pay rate must be greater than zero.'})
        if pay_basis == StaffMember.PayBasis.HOURLY and hours <= 0:
            raise serializers.ValidationError({'hours_per_period': 'Hours per pay period must be greater than zero.'})
        if withholding_percent < 0 or withholding_percent > 100:
            raise serializers.ValidationError({'withholding_percent': 'Withholding must be between 0 and 100 percent.'})
        if benefits < 0 or (pay_basis != StaffMember.PayBasis.DAILY and gross * withholding_percent / Decimal('100') + benefits > gross):
            raise serializers.ValidationError({'benefit_deduction': 'Configured deductions cannot exceed gross pay.'})
        return attrs

    class Meta:
        model = StaffMember
        fields = [
            'id', 'employee_number', 'full_name', 'email', 'phone', 'job_title', 'department',
            'pay_basis', 'pay_basis_display', 'pay_rate', 'hours_per_period', 'withholding_percent',
            'benefit_deduction', 'status', 'status_display', 'hire_date', 'period_days_worked', 'period_gross',
            'period_task_pay', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'employee_number', 'created_at', 'updated_at']


class PayrollLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollLine
        fields = [
            'id', 'worker', 'employee_number', 'worker_name', 'job_title', 'department',
            'pay_basis', 'hours', 'days_worked', 'task_pay', 'gross_pay', 'withholding', 'benefits', 'net_pay',
        ]


class StaffTaskSerializer(serializers.ModelSerializer):
    pay_basis_display = serializers.CharField(source='get_pay_basis_display', read_only=True)
    target_tiers = serializers.ListField(child=serializers.DictField(), required=False)

    def validate(self, attrs):
        pay_basis = attrs.get('pay_basis', self.instance.pay_basis if self.instance else None)
        target_tiers = attrs.get(
            'target_tiers',
            self.instance.target_tiers if self.instance else [],
        )
        if pay_basis == StaffTask.PayBasis.TARGET:
            if not target_tiers:
                raise serializers.ValidationError({'target_tiers': 'Add at least one target and payout for target-based tasks.'})
            validated_tiers = []
            for tier in target_tiers:
                try:
                    if set(tier) != {'target_quantity', 'amount'}:
                        raise ValueError
                    raw_target = tier['target_quantity']
                    if isinstance(raw_target, bool) or str(raw_target).strip() != str(int(raw_target)):
                        raise ValueError
                    target = int(raw_target)
                    amount = Decimal(str(tier['amount']))
                except (KeyError, TypeError, ValueError, ArithmeticError):
                    raise serializers.ValidationError({'target_tiers': 'Each tier needs a whole-number target and a valid payout amount.'})
                if target <= 0 or amount <= 0 or not amount.is_finite():
                    raise serializers.ValidationError({'target_tiers': 'Tier targets and payout amounts must be greater than zero.'})
                validated_tiers.append({'target_quantity': target, 'amount': str(amount)})
            targets = [tier['target_quantity'] for tier in validated_tiers]
            if len(targets) != len(set(targets)):
                raise serializers.ValidationError({'target_tiers': 'Each target quantity must be unique.'})
            attrs['target_tiers'] = sorted(validated_tiers, key=lambda tier: tier['target_quantity'])
            attrs['pay_rate'] = max(Decimal(tier['amount']) for tier in attrs['target_tiers'])
        elif target_tiers:
            attrs['target_tiers'] = []
        if (
            self.instance
            and attrs.get('pay_basis', self.instance.pay_basis) != self.instance.pay_basis
            and self.instance.work_entries.exists()
        ):
            raise serializers.ValidationError({'pay_basis': 'A task pay basis cannot change after work has been recorded.'})
        return attrs

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Enter a task name.')
        return value

    def validate_pay_rate(self, value):
        if value <= 0:
            raise serializers.ValidationError('Task pay rate must be greater than zero.')
        return value

    class Meta:
        model = StaffTask
        fields = ['id', 'name', 'pay_basis', 'pay_basis_display', 'pay_rate', 'target_tiers', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class StaffTaskEntryInputSerializer(serializers.Serializer):
    worker = serializers.PrimaryKeyRelatedField(queryset=StaffMember.objects.all())
    task = serializers.PrimaryKeyRelatedField(queryset=StaffTask.objects.all())
    hours = serializers.DecimalField(max_digits=7, decimal_places=2, min_value=Decimal('0'), required=False, default=Decimal('0'))
    units_worked = serializers.IntegerField(min_value=0, required=False, default=0)

    def validate(self, attrs):
        task = attrs['task']
        if task.pay_basis == StaffTask.PayBasis.HOURLY and attrs['hours'] <= 0:
            raise serializers.ValidationError({'hours': 'Enter hours worked for an hourly task.'})
        if task.pay_basis != StaffTask.PayBasis.HOURLY:
            attrs['hours'] = Decimal('0')
        if task.pay_basis != StaffTask.PayBasis.TARGET:
            attrs['units_worked'] = 0
        return attrs


class StaffTaskEntryRemovalInputSerializer(serializers.Serializer):
    date = serializers.DateField(input_formats=['%Y-%m-%d'])
    worker = serializers.PrimaryKeyRelatedField(queryset=StaffMember.objects.all())
    task = serializers.PrimaryKeyRelatedField(queryset=StaffTask.objects.all())


class StaffTaskEntrySerializer(serializers.ModelSerializer):
    worker_name = serializers.CharField(source='worker.full_name', read_only=True)
    employee_number = serializers.CharField(source='worker.employee_number', read_only=True)
    pay_basis_display = serializers.CharField(source='get_pay_basis_display', read_only=True)

    class Meta:
        model = StaffTaskEntry
        fields = [
            'id', 'worker', 'worker_name', 'employee_number', 'task', 'task_name', 'date', 'assignment_type',
            'pay_basis', 'pay_basis_display', 'pay_rate', 'hours', 'target_tiers', 'units_worked', 'created_at',
        ]
        read_only_fields = fields


class StaffTaskAssignmentSerializer(serializers.ModelSerializer):
    worker_name = serializers.CharField(source='worker.full_name', read_only=True)
    task_name = serializers.CharField(source='task.name', read_only=True)
    pay_basis = serializers.CharField(source='task.pay_basis', read_only=True)
    pay_basis_display = serializers.CharField(source='task.get_pay_basis_display', read_only=True)
    pay_rate = serializers.DecimalField(source='task.pay_rate', max_digits=12, decimal_places=2, read_only=True)
    target_tiers = serializers.ListField(source='task.target_tiers', child=serializers.DictField(), read_only=True)

    def validate(self, attrs):
        worker = attrs.get('worker', self.instance.worker if self.instance else None)
        task = attrs.get('task', self.instance.task if self.instance else None)
        assigned_from = attrs.get('assigned_from', self.instance.assigned_from if self.instance else None)
        is_active = attrs.get('is_active', self.instance.is_active if self.instance else True)
        if worker and worker.status != StaffMember.Status.ACTIVE:
            raise serializers.ValidationError({'worker': 'Only active workers can receive permanent task assignments.'})
        if worker and assigned_from and assigned_from < worker.hire_date:
            raise serializers.ValidationError({'assigned_from': 'The assignment cannot start before the worker’s hire date.'})
        if task and not task.is_active:
            raise serializers.ValidationError({'task': 'Only active tasks can be permanently assigned.'})
        if worker and task and is_active:
            active_assignments = StaffTaskAssignment.objects.filter(worker=worker, task=task, is_active=True)
            if self.instance:
                active_assignments = active_assignments.exclude(pk=self.instance.pk)
            if active_assignments.exists():
                raise serializers.ValidationError({'task': 'This worker is already permanently assigned to this task.'})
        return attrs

    class Meta:
        model = StaffTaskAssignment
        fields = [
            'id', 'worker', 'worker_name', 'task', 'task_name', 'pay_basis', 'pay_basis_display',
            'pay_rate', 'target_tiers', 'assigned_from', 'is_active', 'created_at',
        ]
        read_only_fields = ['id', 'worker_name', 'task_name', 'pay_basis', 'pay_basis_display', 'pay_rate', 'target_tiers', 'created_at']


class StaffAttendanceInputSerializer(serializers.Serializer):
    worker = serializers.PrimaryKeyRelatedField(queryset=StaffMember.objects.all())
    attended = serializers.BooleanField()
    output_quantity = serializers.IntegerField(min_value=0, required=False, default=0)
    daily_wage_override = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal('0.00'), required=False, allow_null=True,
    )

    def validate(self, attrs):
        attrs.setdefault('daily_wage_override', None)
        if not attrs['attended'] or attrs['worker'].pay_basis != StaffMember.PayBasis.DAILY:
            attrs['output_quantity'] = 0
            attrs['daily_wage_override'] = None
        elif attrs['output_quantity'] >= 8 and attrs.get('daily_wage_override') is not None:
            raise serializers.ValidationError({'daily_wage_override': 'A supervisor wage override is only allowed below 8 units.'})
        return attrs


class StaffAttendanceSerializer(serializers.ModelSerializer):
    worker_name = serializers.CharField(source='worker.full_name', read_only=True)
    employee_number = serializers.CharField(source='worker.employee_number', read_only=True)

    class Meta:
        model = StaffAttendance
        fields = ['id', 'worker', 'worker_name', 'employee_number', 'date', 'attended', 'output_quantity', 'daily_wage_override', 'daily_wage', 'created_at', 'updated_at']
        read_only_fields = ['id', 'worker_name', 'employee_number', 'created_at', 'updated_at']


class PayrollRunSerializer(serializers.ModelSerializer):
    lines = PayrollLineSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = PayrollRun
        fields = [
            'id', 'period', 'status', 'status_display', 'worker_count', 'gross_total',
            'withholding_total', 'benefits_total', 'net_total', 'created_at', 'paid_at', 'lines',
        ]
        read_only_fields = fields

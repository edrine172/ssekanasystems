from decimal import Decimal
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers
from .models import BottleCustomerPO, BottleCustomerPOLine, BottleDelivery, BottleDeliveryLine, BottleProduct, Category, ClientMaterial, ClientMaterialPO, ClientMaterialReceipt, Product, Purchase, PurchaseItem, SupplierLedgerEntry
from .sales_serializers import SupplierLedgerEntrySerializer


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
    payments = serializers.SerializerMethodField()

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

    def get_payments(self, purchase):
        entries = [
            entry for entry in purchase.ledger_entries.all()
            if entry.entry_type == SupplierLedgerEntry.EntryType.PAYMENT
        ]
        return SupplierLedgerEntrySerializer(entries, many=True).data

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
        fields = ['id', 'reference', 'supplier', 'supplier_name', 'status', 'items', 'item_count', 'total', 'paid_amount', 'remaining_balance', 'payment_status', 'payments', 'notes', 'expected_delivery', 'ordered_at', 'received_at']
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

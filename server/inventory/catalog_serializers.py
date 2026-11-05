from decimal import Decimal
from rest_framework import serializers
from .models import Category, Customer, Notification, Product, Purchase, StockMovement, Supplier


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

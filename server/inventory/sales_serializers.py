from decimal import Decimal
from rest_framework import serializers
from .models import Customer, CustomerLedgerEntry, Product, Sale, SaleItem, SupplierLedgerEntry


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
    payments = serializers.SerializerMethodField()
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

    def get_payments(self, sale):
        entries = [
            entry for entry in sale.ledger_entries.all()
            if entry.entry_type == CustomerLedgerEntry.EntryType.PAYMENT
        ]
        return CustomerLedgerEntrySerializer(entries, many=True).data

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
            'cash_tendered', 'change_due', 'paid_amount', 'remaining_balance', 'payment_status', 'items', 'payments', 'created_at',
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
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)

    class Meta:
        model = CustomerLedgerEntry
        fields = ['id', 'entry_type', 'entry_type_display', 'amount', 'payment_method', 'payment_method_display', 'reference', 'note', 'sale_reference', 'created_at']


class CustomerPaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    payment_method = serializers.ChoiceField(choices=CustomerLedgerEntry.PaymentMethod.choices, required=False, default='')
    reference = serializers.CharField(max_length=80, required=False, allow_blank=True)
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)
    sale = serializers.PrimaryKeyRelatedField(queryset=Sale.objects.all(), required=False)


class SupplierLedgerEntrySerializer(serializers.ModelSerializer):
    purchase_reference = serializers.CharField(source='purchase.reference', read_only=True, default='')
    entry_type_display = serializers.CharField(source='get_entry_type_display', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)

    class Meta:
        model = SupplierLedgerEntry
        fields = ['id', 'entry_type', 'entry_type_display', 'amount', 'payment_method', 'payment_method_display', 'reference', 'note', 'purchase_reference', 'created_at']


class SupplierPaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    payment_method = serializers.ChoiceField(choices=SupplierLedgerEntry.PaymentMethod.choices, required=False, default='')
    reference = serializers.CharField(max_length=80, required=False, allow_blank=True)
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)

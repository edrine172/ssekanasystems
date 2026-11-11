from decimal import Decimal
from django.db import transaction
from django.db.models import Count, Sum
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from .models import BottleCustomerPO, Category, ClientMaterialPO, Customer, CustomerLedgerEntry, Purchase, Sale, Supplier, SupplierLedgerEntry
from .serializers import BottleCustomerPOSerializer, CategorySerializer, ClientMaterialPOSerializer, CustomerLedgerEntrySerializer, CustomerPaymentSerializer, CustomerSerializer, ProductSerializer, PurchaseSerializer, SaleSerializer, SupplierLedgerEntrySerializer, SupplierPaymentSerializer, SupplierSerializer


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer

    def destroy(self, request, *args, **kwargs):
        category = self.get_object()
        if category.products.exists():
            raise ValidationError({'detail': 'This category is assigned to products. Move those products to another category before deleting it.'})
        return super().destroy(request, *args, **kwargs)


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.prefetch_related('purchases__items__product', 'ledger_entries').all()
    serializer_class = SupplierSerializer

    @action(detail=True, methods=['get'])
    def dashboard(self, request, pk=None):
        supplier = self.get_object()
        purchases = supplier.purchases.select_related('supplier').prefetch_related('items__product', 'ledger_entries').all()
        open_purchases = [purchase for purchase in purchases if purchase.status == Purchase.Status.ORDERED]
        received_purchases = [purchase for purchase in purchases if purchase.status == Purchase.Status.RECEIVED]
        supplier_data = SupplierSerializer(supplier).data
        return Response({
            'supplier': supplier_data,
            'lifetime_spend': supplier_data['lifetime_spend'],
            'outstanding_balance': str(supplier.outstanding_balance),
            'purchase_orders': PurchaseSerializer(purchases[:50], many=True).data,
            'open_order_value': str(sum(
                (item.quantity * item.unit_cost for purchase in open_purchases for item in purchase.items.all()),
                Decimal('0'),
            ).quantize(Decimal('0.01'))),
            'received_orders': len(received_purchases),
            'ledger_entries': SupplierLedgerEntrySerializer(supplier.ledger_entries.select_related('purchase')[:30], many=True).data,
            'supplied_products': ProductSerializer(supplier.products.select_related('category').all(), many=True).data,
        })

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def payments(self, request, pk=None):
        serializer = SupplierPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        supplier = Supplier.objects.select_for_update().get(pk=pk)
        if data['amount'] > supplier.outstanding_balance:
            raise ValidationError({'amount': f'Payment cannot exceed the outstanding balance of {supplier.outstanding_balance}.'})
        supplier.outstanding_balance -= data['amount']
        supplier.save(update_fields=['outstanding_balance'])
        from uuid import uuid4
        entry = SupplierLedgerEntry.objects.create(
            supplier=supplier,
            entry_type=SupplierLedgerEntry.EntryType.PAYMENT,
            amount=data['amount'],
            payment_method=data['payment_method'],
            reference=data.get('reference', '').strip() or f'PAY-{uuid4().hex[:8].upper()}',
            note=data.get('note', '').strip() or 'Supplier payment issued',
        )
        return Response({
            'supplier': SupplierSerializer(supplier).data,
            'ledger_entry': SupplierLedgerEntrySerializer(entry).data,
        }, status=201)


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.annotate(
        _lifetime_revenue=Sum('sales__total'),
        _completed_orders=Count('sales', distinct=True),
    )
    serializer_class = CustomerSerializer
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['name', 'customer_code', 'contact_name', 'email', 'sector']
    ordering_fields = ['name', 'created_at', 'outstanding_balance']
    ordering = ['name']

    def _sale_payment_allocations(self, customer, sales):
        account_sales = [
            sale for sale in sales
            if sale.payment_method == Sale.PaymentMethod.ACCOUNT
            or any(entry.entry_type == CustomerLedgerEntry.EntryType.CHARGE for entry in sale.ledger_entries.all())
        ]
        paid_by_sale = {
            sale.id: sum(
                (entry.amount for entry in sale.ledger_entries.all()
                 if entry.entry_type == CustomerLedgerEntry.EntryType.PAYMENT),
                Decimal('0'),
            )
            for sale in account_sales
        }
        unallocated_payments = customer.ledger_entries.filter(
            entry_type=CustomerLedgerEntry.EntryType.PAYMENT,
            sale__isnull=True,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        for sale in sorted(account_sales, key=lambda row: (row.created_at, row.id)):
            remaining = max(sale.total - paid_by_sale[sale.id], Decimal('0'))
            allocation = min(unallocated_payments, remaining)
            paid_by_sale[sale.id] += allocation
            unallocated_payments -= allocation
            if unallocated_payments <= 0:
                break
        return paid_by_sale, unallocated_payments

    @action(detail=True, methods=['get'])
    def dashboard(self, request, pk=None):
        customer = self.get_object()
        sales = list(customer.sales.prefetch_related('items', 'ledger_entries').all())
        lifetime_revenue = sum((sale.total for sale in sales), Decimal('0'))
        paid_by_sale, _ = self._sale_payment_allocations(customer, sales)
        total_paid_amount = sum(
            (
                sale.total if sale.payment_method != Sale.PaymentMethod.ACCOUNT
                and not any(entry.entry_type == CustomerLedgerEntry.EntryType.CHARGE for entry in sale.ledger_entries.all())
                else paid_by_sale.get(sale.id, Decimal('0'))
                for sale in sales
            ),
            Decimal('0'),
        )
        total_remaining_balance = sum(
            (
                max(sale.total - paid_by_sale.get(sale.id, Decimal('0')), Decimal('0'))
                for sale in sales
                if sale.payment_method == Sale.PaymentMethod.ACCOUNT
                or any(entry.entry_type == CustomerLedgerEntry.EntryType.CHARGE for entry in sale.ledger_entries.all())
            ),
            Decimal('0'),
        )
        ledger_totals = customer.ledger_entries.values('entry_type').annotate(total=Sum('amount'))
        account_totals = {
            row['entry_type']: row['total'] or Decimal('0')
            for row in ledger_totals
        }
        return Response({
            'customer': CustomerSerializer(customer).data,
            'lifetime_revenue': str(lifetime_revenue.quantize(Decimal('0.01'))),
            'completed_orders': len(sales),
            'outstanding_balance': str(customer.outstanding_balance),
            'total_paid_amount': str(total_paid_amount.quantize(Decimal('0.01'))),
            'total_remaining_balance': str(total_remaining_balance.quantize(Decimal('0.01'))),
            'account_charges': str(account_totals.get(CustomerLedgerEntry.EntryType.CHARGE, Decimal('0')).quantize(Decimal('0.01'))),
            'account_payments': str(account_totals.get(CustomerLedgerEntry.EntryType.PAYMENT, Decimal('0')).quantize(Decimal('0.01'))),
            'account_credits': str(account_totals.get(CustomerLedgerEntry.EntryType.CREDIT, Decimal('0')).quantize(Decimal('0.01'))),
            'sales': SaleSerializer(
                sales[:50],
                many=True,
                context={'sale_paid_amounts': paid_by_sale},
            ).data,
            'bottle_purchase_orders': BottleCustomerPOSerializer(
                BottleCustomerPO.objects.filter(customer=customer).select_related('customer').prefetch_related(
                    'items__product__inventory_product',
                    'items__delivery_lines',
                    'deliveries__items__purchase_order_line__product__inventory_product',
                )[:50],
                many=True,
            ).data,
            'client_material_purchase_orders': ClientMaterialPOSerializer(
                ClientMaterialPO.objects.filter(customer=customer)
                .select_related('customer', 'material')
                .prefetch_related('receipts')[:50],
                many=True,
            ).data,
            'ledger_entries': CustomerLedgerEntrySerializer(
                customer.ledger_entries.select_related('sale')[:20],
                many=True,
            ).data,
        })

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def payments(self, request, pk=None):
        serializer = CustomerPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        customer = Customer.objects.select_for_update().get(pk=pk)
        if data['amount'] > customer.outstanding_balance:
            raise ValidationError({'amount': f"Payment cannot exceed the outstanding balance of {customer.outstanding_balance}."})
        customer.outstanding_balance -= data['amount']
        customer.save(update_fields=['outstanding_balance'])
        from uuid import uuid4
        reference = data.get('reference', '').strip() or f"PAY-{uuid4().hex[:8].upper()}"
        note = data.get('note', '').strip() or 'Payment received'
        sales = list(
            Sale.objects.select_for_update()
            .filter(customer=customer)
            .prefetch_related('ledger_entries')
            .order_by('created_at', 'id')
        )
        sales = [
            sale for sale in sales
            if sale.payment_method == Sale.PaymentMethod.ACCOUNT
            or any(entry.entry_type == CustomerLedgerEntry.EntryType.CHARGE for entry in sale.ledger_entries.all())
        ]
        paid_by_sale, _ = self._sale_payment_allocations(customer, sales)
        payment_remaining = data['amount']
        new_entries = []
        target_sale = data.get('sale')
        if target_sale is not None:
            target_sale = next((sale for sale in sales if sale.pk == target_sale.pk), None)
            if target_sale is None:
                raise ValidationError({'sale': 'Select an on-account sale belonging to this customer.'})
            sale_balance = max(target_sale.total - paid_by_sale.get(target_sale.id, Decimal('0')), Decimal('0'))
            if payment_remaining > sale_balance:
                raise ValidationError({'amount': f'Payment cannot exceed this sale balance of {sale_balance:.2f}.'})
            new_entries.append(CustomerLedgerEntry.objects.create(
                customer=customer,
                sale=target_sale,
                entry_type=CustomerLedgerEntry.EntryType.PAYMENT,
                amount=payment_remaining,
                payment_method=data['payment_method'],
                reference=reference,
                note=note,
            ))
            payment_remaining = Decimal('0')

        for sale in sales:
            if target_sale is not None:
                break
            sale_balance = max(sale.total - paid_by_sale.get(sale.id, Decimal('0')), Decimal('0'))
            amount_for_sale = min(payment_remaining, sale_balance)
            if amount_for_sale <= 0:
                continue
            new_entries.append(CustomerLedgerEntry.objects.create(
                customer=customer,
                sale=sale,
                entry_type=CustomerLedgerEntry.EntryType.PAYMENT,
                amount=amount_for_sale,
                payment_method=data['payment_method'],
                reference=reference,
                note=note,
            ))
            payment_remaining -= amount_for_sale
            if payment_remaining <= 0:
                break
        if payment_remaining > 0 or not new_entries:
            new_entries.append(CustomerLedgerEntry.objects.create(
                customer=customer,
                entry_type=CustomerLedgerEntry.EntryType.PAYMENT,
                amount=payment_remaining if payment_remaining > 0 else data['amount'],
                payment_method=data['payment_method'],
                reference=reference,
                note=note,
            ))
        return Response({
            'customer': CustomerSerializer(customer).data,
            'ledger_entry': CustomerLedgerEntrySerializer(new_entries[0]).data,
            'ledger_entries': CustomerLedgerEntrySerializer(new_entries, many=True).data,
        }, status=201)

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from .models import BottleCustomerPO, BottleCustomerPOLine, BottleDelivery, BottleDeliveryLine, BottleProduct, ClientMaterial, ClientMaterialPO, ClientMaterialReceipt, Customer, CustomerLedgerEntry, Product, Purchase, PurchaseItem, Sale, SaleItem, StockMovement, Supplier, SupplierLedgerEntry
from .serializers import BottleCustomerPOSerializer, BottleDeliverySerializer, BottleProductSerializer, ClientMaterialPOSerializer, ClientMaterialReceiptInputSerializer, ClientMaterialSerializer, ProductSerializer, PurchaseSerializer, SaleCheckoutSerializer, SaleSerializer, StockAdjustmentSerializer, StockMovementSerializer, SupplierLedgerEntrySerializer, SupplierPaymentSerializer
from .date_ranges import day_range
from .reports import build_report_summary


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.select_related('category', 'supplier').all()
    serializer_class = ProductSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['name', 'sku', 'category__name']
    ordering_fields = ['name', 'quantity', 'unit_price', 'updated_at']
    ordering = ['name']

    def get_queryset(self):
        queryset = super().get_queryset()
        category = self.request.query_params.get('category')
        supplier = self.request.query_params.get('supplier')
        status = self.request.query_params.get('stock_status')
        active = self.request.query_params.get('active')

        if active == 'true':
            queryset = queryset.filter(is_active=True)
        elif active == 'false':
            queryset = queryset.filter(is_active=False)
        if category and category.isdigit():
            queryset = queryset.filter(category_id=category)
        if supplier == 'none':
            queryset = queryset.filter(supplier__isnull=True)
        elif supplier and supplier.isdigit():
            queryset = queryset.filter(supplier_id=supplier)
        if status == 'in_stock':
            queryset = queryset.filter(quantity__gt=F('reorder_level'))
        elif status == 'low_stock':
            queryset = queryset.filter(quantity__gt=0, quantity__lte=F('reorder_level'))
        elif status == 'out_of_stock':
            queryset = queryset.filter(quantity=0)
        return queryset

    def destroy(self, request, *args, **kwargs):
        product = self.get_object()
        has_history = (
            product.sale_items.exists()
            or product.purchase_items.exists()
            or product.movements.exists()
        )
        if has_history:
            return Response(
                {'detail': 'This product is linked to sales, purchases, or inventory movements. Deactivate it instead to preserve its history.'},
                status=409,
            )
        return super().destroy(request, *args, **kwargs)


class StockMovementViewSet(viewsets.ModelViewSet):
    queryset = StockMovement.objects.select_related('product').all()
    serializer_class = StockMovementSerializer
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        queryset = super().get_queryset()
        days = self.request.query_params.get('days')
        month = self.request.query_params.get('month')
        selected_date = self.request.query_params.get('date')
        if selected_date is not None:
            if days is not None or month is not None:
                raise ValidationError({'date': 'Use a single day, a rolling range, or a calendar month.'})
            try:
                parsed_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
            except (TypeError, ValueError):
                raise ValidationError({'date': 'Enter a date in YYYY-MM-DD format.'})
            if parsed_date.isoformat() != selected_date:
                raise ValidationError({'date': 'Enter a date in YYYY-MM-DD format.'})
            start_at, end_at = day_range(parsed_date)
            return queryset.filter(created_at__gte=start_at, created_at__lt=end_at)
        if month is not None:
            if days is not None:
                raise ValidationError({'month': 'Use either a rolling range or a calendar month.'})
            try:
                parsed_month = datetime.strptime(month, '%Y-%m')
            except (TypeError, ValueError):
                raise ValidationError({'month': 'Enter a month in YYYY-MM format.'})
            if parsed_month.strftime('%Y-%m') != month:
                raise ValidationError({'month': 'Enter a month in YYYY-MM format.'})
            start_at, end_at = day_range(parsed_month.date().replace(day=1), (parsed_month.date().replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1))
            return queryset.filter(created_at__gte=start_at, created_at__lt=end_at)
        if days is None:
            return queryset
        allowed_ranges = {1, 7, 30, 90, 180, 365, 730, 1825, 3650, 18250, 36500, 73000}
        try:
            day_count = int(days)
        except (TypeError, ValueError):
            raise ValidationError({'days': 'Choose a supported audit history range.'})
        if day_count not in allowed_ranges:
            raise ValidationError({'days': 'Choose a supported audit history range.'})
        return queryset.filter(created_at__gte=timezone.now() - timedelta(days=day_count))

    @transaction.atomic
    def perform_create(self, serializer):
        from rest_framework.exceptions import ValidationError
        product = Product.objects.select_for_update().get(pk=serializer.validated_data['product'].pk)
        movement_type = serializer.validated_data['movement_type']
        quantity = serializer.validated_data['quantity']
        delta = quantity if movement_type in ['inbound', 'return'] else -quantity if movement_type == 'outbound' else quantity
        if product.quantity + delta < 0:
            raise ValidationError({'quantity': 'This movement would reduce stock below zero.'})
        product.quantity += delta
        product.save(update_fields=['quantity', 'updated_at'])
        serializer.save(product=product)


class PurchaseViewSet(viewsets.ModelViewSet):
    queryset = Purchase.objects.select_related('supplier').prefetch_related('items__product', 'ledger_entries').all()
    serializer_class = PurchaseSerializer
    http_method_names = ['get', 'post', 'head', 'options']

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def receive(self, request, pk=None):
        purchase = Purchase.objects.select_for_update().select_related('supplier').get(pk=pk)
        if purchase.status != Purchase.Status.ORDERED:
            raise ValidationError({'status': 'Only ordered purchases can be received.'})

        items = PurchaseItem.objects.filter(purchase=purchase).order_by('product_id')
        received_value = Decimal('0')
        for item in items:
            product = Product.objects.select_for_update().get(pk=item.product_id)
            product.quantity += item.quantity
            product.cost_price = item.unit_cost
            product.save(update_fields=['quantity', 'cost_price', 'updated_at'])
            received_value += item.quantity * item.unit_cost
            StockMovement.objects.create(
                product=product,
                movement_type=StockMovement.MovementType.INBOUND,
                quantity=item.quantity,
                note=f'Received from {purchase.supplier.name}',
                reference=purchase.reference,
            )
        purchase.status = Purchase.Status.RECEIVED
        purchase.received_at = timezone.now()
        purchase.save(update_fields=['status', 'received_at'])
        supplier = Supplier.objects.select_for_update().get(pk=purchase.supplier_id)
        supplier.outstanding_balance += received_value
        supplier.save(update_fields=['outstanding_balance'])
        SupplierLedgerEntry.objects.create(
            supplier=supplier,
            purchase=purchase,
            entry_type=SupplierLedgerEntry.EntryType.CHARGE,
            amount=received_value,
            reference=purchase.reference,
            note='Goods received; payable recorded',
        )
        return Response(self.get_serializer(purchase).data)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def payments(self, request, pk=None):
        serializer = SupplierPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        purchase = self.get_object()
        purchase = Purchase.objects.select_for_update().select_related('supplier').get(pk=purchase.pk)
        if purchase.status != Purchase.Status.RECEIVED:
            raise ValidationError({'status': 'A purchase must be received before a supplier payment can be recorded.'})

        purchase_total = sum(
            (item.quantity * item.unit_cost for item in purchase.items.all()),
            Decimal('0'),
        )
        paid_amount = purchase.ledger_entries.filter(
            entry_type=SupplierLedgerEntry.EntryType.PAYMENT,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        remaining_balance = max(purchase_total - paid_amount, Decimal('0'))
        if data['amount'] > remaining_balance:
            raise ValidationError({'amount': f'Payment cannot exceed this purchase balance of {remaining_balance:.2f}.'})

        supplier = Supplier.objects.select_for_update().get(pk=purchase.supplier_id)
        if data['amount'] > supplier.outstanding_balance:
            raise ValidationError({
                'amount': f'Payment cannot exceed the supplier account balance of {supplier.outstanding_balance:.2f}.',
            })
        supplier.outstanding_balance -= data['amount']
        supplier.save(update_fields=['outstanding_balance'])
        from uuid import uuid4
        entry = SupplierLedgerEntry.objects.create(
            supplier=supplier,
            purchase=purchase,
            entry_type=SupplierLedgerEntry.EntryType.PAYMENT,
            amount=data['amount'],
            payment_method=data['payment_method'],
            reference=data.get('reference', '').strip() or f'PAY-{uuid4().hex[:8].upper()}',
            note=data.get('note', '').strip() or f'Supplier payment confirmed for {purchase.reference}',
        )
        return Response({
            'purchase': self.get_serializer(purchase).data,
            'ledger_entry': SupplierLedgerEntrySerializer(entry).data,
        }, status=201)


class BottleProductViewSet(viewsets.ModelViewSet):
    queryset = BottleProduct.objects.select_related('inventory_product').all()
    serializer_class = BottleProductSerializer
    http_method_names = ['get', 'post', 'patch', 'head', 'options']


class BottleCustomerPOViewSet(viewsets.ModelViewSet):
    queryset = BottleCustomerPO.objects.select_related('customer').prefetch_related(
        'items__product__inventory_product', 'items__delivery_lines',
        'deliveries__items__purchase_order_line__product__inventory_product',
    ).all()
    serializer_class = BottleCustomerPOSerializer
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        purchase_order = BottleCustomerPO.objects.select_for_update().get(pk=self.get_object().pk)
        delivered_by_product = BottleDeliveryLine.objects.filter(
            purchase_order_line__purchase_order=purchase_order,
        ).values(
            'purchase_order_line__product__inventory_product_id',
        ).annotate(
            total=Sum('quantity'),
        ).order_by('purchase_order_line__product__inventory_product_id')

        for row in delivered_by_product:
            quantity = row['total']
            product = Product.objects.select_for_update().get(
                pk=row['purchase_order_line__product__inventory_product_id'],
            )
            product.quantity += quantity
            product.save(update_fields=['quantity', 'updated_at'])
            BottleProduct.objects.filter(inventory_product_id=product.id).update(quantity=product.quantity)
            StockMovement.objects.create(
                product=product,
                movement_type=StockMovement.MovementType.RETURN,
                quantity=quantity,
                note=f'Returned from cancelled PO {purchase_order.reference}',
                reference=f'{purchase_order.reference}-RETURN',
            )

        BottleDeliveryLine.objects.filter(
            purchase_order_line__purchase_order=purchase_order,
        ).delete()
        purchase_order.deliveries.all().delete()
        purchase_order.items.all().delete()
        purchase_order.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def deliver(self, request, pk=None):
        from uuid import uuid4

        serializer = BottleDeliverySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        purchase_order = BottleCustomerPO.objects.select_for_update().get(pk=pk)
        lines_by_id = {
            line.id: line for line in BottleCustomerPOLine.objects.select_for_update()
            .filter(purchase_order=purchase_order)
            .select_related('product__inventory_product')
            .order_by('product_id')
        }
        delivery_items = serializer.validated_data['items']
        prepared = []
        for delivery_item in delivery_items:
            line = lines_by_id.get(delivery_item['purchase_order_line'])
            if line is None:
                raise ValidationError({'items': 'A delivery line does not belong to this customer PO.'})
            delivered = BottleDeliveryLine.objects.filter(purchase_order_line=line).aggregate(
                total=Sum('quantity'),
            )['total'] or 0
            remaining = line.quantity - delivered
            if delivery_item['quantity'] > remaining:
                raise ValidationError({
                    'items': f'Only {remaining} units remain for {line.product.sku} on this PO.',
                })
            prepared.append((line, delivery_item['quantity']))

        product_ids = sorted({line.product.inventory_product_id for line, _ in prepared})
        products = {
            product.id: product for product in Product.objects.select_for_update()
            .filter(pk__in=product_ids).order_by('id')
        }
        for line, quantity in prepared:
            product = products[line.product.inventory_product_id]
            if product.quantity < quantity:
                raise ValidationError({
                    'items': f'Only {product.quantity} units of {product.sku} are in product inventory.',
                })

        delivery = BottleDelivery.objects.create(
            reference=f"BD-{timezone.now().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}",
            purchase_order=purchase_order,
            notes=serializer.validated_data.get('notes', '').strip(),
        )
        for line, quantity in prepared:
            product = products[line.product.inventory_product_id]
            product.quantity -= quantity
            product.save(update_fields=['quantity', 'updated_at'])
            BottleProduct.objects.filter(inventory_product_id=product.id).update(quantity=product.quantity)
            BottleDeliveryLine.objects.create(
                delivery=delivery,
                purchase_order_line=line,
                quantity=quantity,
            )
            StockMovement.objects.create(
                product=product,
                movement_type=StockMovement.MovementType.OUTBOUND,
                quantity=quantity,
                note=f'Delivered to {purchase_order.customer.name}',
                reference=delivery.reference,
            )

        return Response(self.get_serializer(purchase_order).data)


class ClientMaterialViewSet(viewsets.ModelViewSet):
    queryset = ClientMaterial.objects.all()
    serializer_class = ClientMaterialSerializer
    http_method_names = ['get', 'post', 'head', 'options']


class ClientMaterialPOViewSet(viewsets.ModelViewSet):
    queryset = ClientMaterialPO.objects.select_related('customer', 'material').prefetch_related('receipts').all()
    serializer_class = ClientMaterialPOSerializer
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        purchase_order = ClientMaterialPO.objects.select_for_update().get(pk=self.get_object().pk)
        material = ClientMaterial.objects.select_for_update().get(pk=purchase_order.material_id)
        received = purchase_order.receipts.aggregate(total=Sum('quantity'))['total'] or Decimal('0')
        if material.quantity < received:
            raise ValidationError({
                'purchase_order': (
                    f'Cannot delete this PO because {received - material.quantity} '
                    f'{material.unit} of its received stock has already been used.'
                ),
            })

        material.quantity -= received
        material.save(update_fields=['quantity'])
        purchase_order.receipts.all().delete()
        purchase_order.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def receive(self, request, pk=None):
        from uuid import uuid4

        serializer = ClientMaterialReceiptInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        purchase_order = ClientMaterialPO.objects.select_for_update().select_related('material').get(pk=pk)
        received = purchase_order.receipts.aggregate(total=Sum('quantity'))['total'] or Decimal('0')
        remaining = purchase_order.quantity - received
        quantity = serializer.validated_data['quantity']
        if quantity > remaining:
            raise ValidationError({'quantity': f'Only {remaining} {purchase_order.material.unit} remain on this PO.'})

        material = ClientMaterial.objects.select_for_update().get(pk=purchase_order.material_id)
        material.quantity += quantity
        material.save(update_fields=['quantity'])
        ClientMaterialReceipt.objects.create(
            reference=f"CMR-{timezone.now().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}",
            purchase_order=purchase_order,
            quantity=quantity,
            notes=serializer.validated_data.get('notes', '').strip(),
        )
        return Response(self.get_serializer(purchase_order).data)


class SaleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Sale.objects.prefetch_related('items', 'ledger_entries').all()
    serializer_class = SaleSerializer


@api_view(['POST'])
@transaction.atomic
def checkout(request):
    serializer = SaleCheckoutSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    cart_items = data['items']
    product_ids = [item['product'].id for item in cart_items]
    locked_products = Product.objects.select_for_update().filter(pk__in=product_ids).order_by('id')
    products = {product.id: product for product in locked_products}
    for item in cart_items:
        product = products.get(item['product'].id)
        if product is None or not product.is_active:
            raise ValidationError({'items': 'One or more products are no longer available.'})
        if product.quantity < item['quantity']:
            raise ValidationError({'items': f'Only {product.quantity} units of {product.sku} are in stock.'})
    unit_prices = {
        item['product'].id: item.get('unit_price', products[item['product'].id].unit_price)
        for item in cart_items
    }

    customer = data.get('customer')
    if customer is not None:
        customer = Customer.objects.select_for_update().get(pk=customer.pk)
        if not customer.is_active:
            raise ValidationError({'customer': 'This customer account is inactive.'})

    cent = Decimal('0.01')
    tax_rate = Decimal('0')
    subtotal = sum(
        (unit_prices[item['product'].id] * item['quantity'] for item in cart_items),
        Decimal('0'),
    ).quantize(cent, rounding=ROUND_HALF_UP)
    discount_percent = data['discount_percent']
    discount_amount = (subtotal * discount_percent / Decimal('100')).quantize(cent, rounding=ROUND_HALF_UP)
    taxable_subtotal = subtotal - discount_amount
    tax_amount = (taxable_subtotal * tax_rate / Decimal('100')).quantize(cent, rounding=ROUND_HALF_UP)
    total = subtotal - discount_amount + tax_amount
    if data['payment_method'] == Sale.PaymentMethod.ACCOUNT:
        if customer.credit_limit <= 0:
            raise ValidationError({'customer': 'This customer does not have an approved credit limit.'})
        if customer.outstanding_balance + total > customer.credit_limit:
            available_credit = max(customer.credit_limit - customer.outstanding_balance, Decimal('0'))
            raise ValidationError({'customer': f'Available credit is {available_credit}; this sale totals {total}.'})
    cash_tendered = data.get('cash_tendered')
    if data['payment_method'] == Sale.PaymentMethod.CASH:
        if cash_tendered is None:
            raise ValidationError({'cash_tendered': 'Enter the cash received for this sale.'})
        if cash_tendered <= 0:
            raise ValidationError({'cash_tendered': 'Cash received must be greater than zero.'})
        remaining_balance = max(total - cash_tendered, Decimal('0'))
        if remaining_balance > 0:
            if customer is None:
                raise ValidationError({'customer': 'Select a customer to record the remaining balance.'})
            if customer.credit_limit <= 0:
                raise ValidationError({'customer': 'This customer does not have an approved credit limit.'})
            if customer.outstanding_balance + remaining_balance > customer.credit_limit:
                available_credit = max(customer.credit_limit - customer.outstanding_balance, Decimal('0'))
                raise ValidationError({'customer': f'Available credit is {available_credit}; the remaining balance is {remaining_balance}.'})
    else:
        cash_tendered = None

    from uuid import uuid4
    receipt_number = f"SALE-{timezone.now().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"
    sale = Sale.objects.create(
        receipt_number=receipt_number,
        customer=customer,
        customer_name=(customer.name if customer else data.get('customer_name', '').strip()) or 'Walk-in Customer',
        payment_method=data['payment_method'],
        subtotal=subtotal,
        discount_percent=discount_percent,
        discount_amount=discount_amount,
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        total=total,
        cash_tendered=cash_tendered,
        change_due=(cash_tendered - total) if cash_tendered is not None else Decimal('0'),
    )
    sale_items = []
    movements = []
    for item in cart_items:
        product = products[item['product'].id]
        quantity = item['quantity']
        sale_items.append(SaleItem(
            sale=sale,
            product=product,
            product_name=product.name,
            product_sku=product.sku,
            quantity=quantity,
            unit_price=unit_prices[product.id],
            unit_cost=product.cost_price,
        ))
        product.quantity -= quantity
        product.save(update_fields=['quantity', 'updated_at'])
        movements.append(StockMovement(
            product=product,
            movement_type=StockMovement.MovementType.OUTBOUND,
            quantity=quantity,
            note=f'POS sale to {sale.customer_name}',
            reference=receipt_number,
        ))
    SaleItem.objects.bulk_create(sale_items)
    StockMovement.objects.bulk_create(movements)
    if data['payment_method'] == Sale.PaymentMethod.ACCOUNT:
        customer.outstanding_balance += total
        customer.save(update_fields=['outstanding_balance'])
        CustomerLedgerEntry.objects.create(
            customer=customer,
            sale=sale,
            entry_type=CustomerLedgerEntry.EntryType.CHARGE,
            amount=total,
            reference=receipt_number,
            note='POS sale on account',
        )
    elif cash_tendered is not None and cash_tendered < total:
        remaining_balance = total - cash_tendered
        customer.outstanding_balance += remaining_balance
        customer.save(update_fields=['outstanding_balance'])
        CustomerLedgerEntry.objects.create(
            customer=customer,
            sale=sale,
            entry_type=CustomerLedgerEntry.EntryType.CHARGE,
            amount=total,
            reference=receipt_number,
            note='POS sale with partial payment',
        )
        CustomerLedgerEntry.objects.create(
            customer=customer,
            sale=sale,
            entry_type=CustomerLedgerEntry.EntryType.PAYMENT,
            amount=cash_tendered,
            reference=receipt_number,
            note='POS partial cash payment',
        )
    sale = Sale.objects.prefetch_related('items', 'ledger_entries').get(pk=sale.pk)
    return Response(SaleSerializer(sale).data, status=201)


@api_view(['POST'])
@transaction.atomic
def inventory_adjustment(request):
    serializer = StockAdjustmentSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    product = Product.objects.select_for_update().get(pk=data['product'].pk)
    adjustment_type = data['adjustment_type']
    if adjustment_type == 'count':
        delta = data['counted_quantity'] - product.quantity
    else:
        quantity = data['quantity']
        delta = quantity if adjustment_type == 'increase' else -quantity
    if delta == 0:
        raise ValidationError({'counted_quantity': 'The counted quantity matches current stock; no adjustment is needed.'})
    if product.quantity + delta < 0:
        raise ValidationError({'quantity': 'This adjustment would reduce stock below zero.'})

    product.quantity += delta
    product.save(update_fields=['quantity', 'updated_at'])
    note = data['reason']
    if data.get('notes'):
        note = f"{note}: {data['notes']}"
    movement = StockMovement.objects.create(
        product=product,
        movement_type=StockMovement.MovementType.ADJUSTMENT,
        quantity=delta,
        note=note,
        reference=data.get('reference', ''),
    )
    return Response(StockMovementSerializer(movement).data, status=201)


@api_view(['GET'])
def purchase_summary(request):
    month_start = timezone.localdate().replace(day=1)
    month_start_at, _ = day_range(month_start)
    open_purchases = Purchase.objects.filter(status=Purchase.Status.ORDERED).prefetch_related('items')
    received_this_month = Purchase.objects.filter(
        status=Purchase.Status.RECEIVED,
        received_at__gte=month_start_at,
    ).prefetch_related('items')
    open_value = sum(
        (item.quantity * item.unit_cost for purchase in open_purchases for item in purchase.items.all()),
        Decimal('0'),
    )
    monthly_spend = sum(
        (item.quantity * item.unit_cost for purchase in received_this_month for item in purchase.items.all()),
        Decimal('0'),
    )
    return Response({
        'total_orders': Purchase.objects.count(),
        'open_orders': open_purchases.count(),
        'received_this_month': received_this_month.count(),
        'open_value': str(open_value),
        'spent_this_month': str(monthly_spend),
        'recent_purchases': PurchaseSerializer(
            Purchase.objects.select_related('supplier').prefetch_related('items__product', 'ledger_entries')[:8],
            many=True,
        ).data,
    })


@api_view(['GET'])
def sales_summary(request):
    today = timezone.localdate()
    today_start, today_end = day_range(today)
    todays_sales = Sale.objects.filter(created_at__gte=today_start, created_at__lt=today_end)
    totals = todays_sales.aggregate(total=Sum('total'))
    return Response({
        'today_sales': str(totals['total'] or Decimal('0')),
        'transactions_today': todays_sales.count(),
        'recent_sales': SaleSerializer(
            Sale.objects.prefetch_related('items', 'ledger_entries')[:8],
            many=True,
        ).data,
    })


@api_view(['GET'])
def reports_summary(request):
    selected_date = request.query_params.get('date')
    if selected_date is not None:
        try:
            report_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            raise ValidationError({'date': 'Enter a date in YYYY-MM-DD format.'})
        if report_date.isoformat() != selected_date:
            raise ValidationError({'date': 'Enter a date in YYYY-MM-DD format.'})
        return Response(build_report_summary(1, report_date, report_date))

    month = request.query_params.get('month')
    if month is not None:
        try:
            month_start = datetime.strptime(month, '%Y-%m').date().replace(day=1)
        except ValueError:
            raise ValidationError({'month': 'Enter a month in YYYY-MM format.'})
        if month_start.strftime('%Y-%m') != month:
            raise ValidationError({'month': 'Enter a month in YYYY-MM format.'})
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        month_end = next_month - timedelta(days=1)
        month_days = (month_end - month_start).days + 1
        return Response(build_report_summary(month_days, month_start, month_end))

    range_days = request.query_params.get('range', '30d')
    days = {
        '1d': 1, '7d': 7, '30d': 30, '90d': 90, '180d': 180, '365d': 365,
        '730d': 730, '1825d': 1825, '3650d': 3650, '18250d': 18250,
        '36500d': 36500, '73000d': 73000,
    }.get(range_days, 30)
    return Response(build_report_summary(days))

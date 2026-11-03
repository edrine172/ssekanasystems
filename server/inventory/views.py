from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import json
from math import isfinite
import re
from urllib.error import URLError
from urllib.request import urlopen

from django.core.cache import cache
from django.db import transaction
from django.db.models import Case, Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value, When
from django.db.models.functions import Abs, TruncDate
from django.utils import timezone
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
from .models import BalanceSheetAccount, BottleCustomerPO, BottleCustomerPOLine, BottleDelivery, BottleDeliveryLine, BottleProduct, Category, ClientMaterial, ClientMaterialPO, ClientMaterialReceipt, Customer, CustomerLedgerEntry, Expense, ExpenseBudget, Notification, PayrollLine, PayrollRun, Product, Purchase, PurchaseItem, Sale, SaleItem, SecurityAuditEvent, StaffAttendance, StaffMember, StaffTask, StaffTaskAssignment, StaffTaskEntry, StockMovement, Supplier, SupplierLedgerEntry, SystemSetting
from .serializers import BalanceSheetAccountSerializer, BottleCustomerPOSerializer, BottleDeliverySerializer, BottleProductSerializer, CategorySerializer, ClientMaterialPOSerializer, ClientMaterialReceiptInputSerializer, ClientMaterialSerializer, CustomerLedgerEntrySerializer, CustomerPaymentSerializer, CustomerSerializer, ExpenseBudgetSerializer, ExpenseSerializer, NotificationSerializer, PayrollRunSerializer, ProductSerializer, PurchaseSerializer, SaleCheckoutSerializer, SaleSerializer, StaffAttendanceInputSerializer, StaffAttendanceSerializer, StaffMemberSerializer, StaffTaskAssignmentSerializer, StaffTaskEntryInputSerializer, StaffTaskEntryRemovalInputSerializer, StaffTaskEntrySerializer, StaffTaskSerializer, StockAdjustmentSerializer, StockMovementSerializer, SupplierLedgerEntrySerializer, SupplierPaymentSerializer, SupplierSerializer
from .date_ranges import day_range
from .reports import build_report_summary
from .permissions import RoleModelPermissions

DAILY_WAGE_TIERS = (
    (15, Decimal('7000.00')),
    (12, Decimal('6000.00')),
    (10, Decimal('5000.00')),
    (8, Decimal('4000.00')),
)
SUNDAY_WAGE_TIERS = (
    (15, Decimal('7000.00')),
    (12, Decimal('6000.00')),
    (8, Decimal('4000.00')),
)


def daily_attendance_wage(work_date, attended, output_quantity, wage_override=None):
    if not attended:
        return Decimal('0.00')
    wage_tiers = SUNDAY_WAGE_TIERS if work_date.weekday() == 6 else DAILY_WAGE_TIERS
    return next(
        (wage for units, wage in wage_tiers if output_quantity >= units),
        wage_override if wage_override is not None else Decimal('0.00'),
    )


def refresh_daily_attendance_wage(worker, work_date):
    attendance = StaffAttendance.objects.filter(worker=worker, date=work_date).first()
    if not attendance:
        return
    if (
        attendance.attended
        and worker.pay_basis == StaffMember.PayBasis.DAILY
        and not StaffTaskEntry.objects.filter(worker=worker, date=work_date).exists()
    ):
        wage = daily_attendance_wage(work_date, True, attendance.output_quantity, attendance.daily_wage_override)
    else:
        wage = Decimal('0.00')
    if attendance.daily_wage != wage:
        attendance.daily_wage = wage
        attendance.save(update_fields=['daily_wage'])


def task_pay_totals(entries):
    totals = {}
    monthly_rates = {}
    for entry in entries:
        if entry.pay_basis == StaffTask.PayBasis.DAILY:
            totals[entry.worker_id] = totals.get(entry.worker_id, Decimal('0')) + entry.pay_rate
        elif entry.pay_basis == StaffTask.PayBasis.HOURLY:
            totals[entry.worker_id] = totals.get(entry.worker_id, Decimal('0')) + entry.pay_rate * entry.hours
        elif entry.pay_basis == StaffTask.PayBasis.TARGET:
            reached_tiers = [
                tier for tier in entry.target_tiers
                if entry.units_worked >= tier['target_quantity']
            ]
            payout = max(
                (Decimal(str(tier['amount'])) for tier in reached_tiers),
                default=Decimal('0'),
            )
            totals[entry.worker_id] = totals.get(entry.worker_id, Decimal('0')) + payout
        else:
            monthly_rates.setdefault((entry.worker_id, entry.task_id), entry.pay_rate)
    for (worker_id, _task_id), rate in monthly_rates.items():
        totals[worker_id] = totals.get(worker_id, Decimal('0')) + rate
    return {
        worker_id: amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        for worker_id, amount in totals.items()
    }


def refresh_unpaid_worker_payroll(worker):
    cent = Decimal('0.01')
    runs = PayrollRun.objects.select_for_update().filter(
        status=PayrollRun.Status.SCHEDULED,
        lines__worker=worker,
    ).distinct().order_by('period')
    for run in runs:
        line = PayrollLine.objects.select_for_update().get(run=run, worker=worker)
        year, month = map(int, run.period.split('-'))
        attendance = StaffAttendance.objects.filter(
            worker=worker,
            date__year=year,
            date__month=month,
            attended=True,
        ).aggregate(days_worked=Count('id'), gross=Sum('daily_wage'))
        hours = worker.hours_per_period if worker.pay_basis == StaffMember.PayBasis.HOURLY else Decimal('0')
        if worker.pay_basis == StaffMember.PayBasis.DAILY:
            base_gross = attendance['gross'] or Decimal('0.00')
        elif worker.pay_basis == StaffMember.PayBasis.MONTHLY:
            base_gross = worker.pay_rate
        else:
            base_gross = worker.pay_rate * hours
        gross = (base_gross + line.task_pay).quantize(cent, rounding=ROUND_HALF_UP)
        withholding = (gross * worker.withholding_percent / Decimal('100')).quantize(cent, rounding=ROUND_HALF_UP)
        benefits = min(worker.benefit_deduction, gross) if worker.pay_basis == StaffMember.PayBasis.DAILY else worker.benefit_deduction
        if withholding + benefits > gross:
            raise ValidationError({'worker': f'Deductions exceed gross pay for {worker.employee_number}.'})
        line.pay_basis = worker.pay_basis
        line.hours = hours
        line.days_worked = attendance['days_worked']
        line.gross_pay = gross
        line.withholding = withholding
        line.benefits = benefits
        line.net_pay = gross - withholding - benefits
        line.save(update_fields=[
            'pay_basis', 'hours', 'days_worked', 'gross_pay', 'withholding', 'benefits', 'net_pay',
        ])
        totals = run.lines.aggregate(
            gross_total=Sum('gross_pay'),
            withholding_total=Sum('withholding'),
            benefits_total=Sum('benefits'),
            net_total=Sum('net_pay'),
        )
        run.gross_total = totals['gross_total'] or Decimal('0.00')
        run.withholding_total = totals['withholding_total'] or Decimal('0.00')
        run.benefits_total = totals['benefits_total'] or Decimal('0.00')
        run.net_total = totals['net_total'] or Decimal('0.00')
        run.save(update_fields=['gross_total', 'withholding_total', 'benefits_total', 'net_total'])


SETTINGS_DEFAULTS = {
    'organization': {
        'business_name': 'Apex Supply Co.',
        'tax_id': '',
        'currency': 'UGX',
        'timezone': 'Africa/Kampala',
        'default_warehouse': 'Main Warehouse',
    },
    'operations': {
        'reorder_threshold': 15,
        'allow_negative_stock': True,
        'auto_purchase_drafts': True,
        'default_payment_terms': 'Net 30',
    },
    'security': {
        'require_two_factor': False,
        'session_timeout_minutes': 30,
        'audit_retention_days': 365,
    },
    'integrations': {
        'quickbooks_enabled': True,
        'stripe_enabled': True,
        'webhooks_enabled': True,
    },
}


@api_view(['GET', 'PATCH'])
@permission_classes([RoleModelPermissions])
def system_settings(request):
    settings = {category: values.copy() for category, values in SETTINGS_DEFAULTS.items()}
    for item in SystemSetting.objects.all():
        if item.category in settings and item.key in settings[item.category]:
            settings[item.category][item.key] = item.value

    if request.method == 'PATCH':
        updates = request.data.get('settings')
        if not isinstance(updates, dict) or not updates:
            raise ValidationError({'settings': 'Provide at least one category of settings to update.'})

        validated = []
        for category, values in updates.items():
            if category not in SETTINGS_DEFAULTS or not isinstance(values, dict) or not values:
                raise ValidationError({'settings': f'Unknown or empty settings category: {category}.'})
            for key, value in values.items():
                if key not in SETTINGS_DEFAULTS[category]:
                    raise ValidationError({'settings': f'Unknown setting: {category}.{key}.'})
                if category == 'organization' and key == 'currency' and (
                    not isinstance(value, str) or not re.fullmatch(r'[A-Z]{3}', value)
                ):
                    raise ValidationError({'settings': 'Currency must be a three-letter uppercase currency code.'})
                default = SETTINGS_DEFAULTS[category][key]
                if type(value) is not type(default):
                    raise ValidationError({'settings': f'{category}.{key} has an invalid value type.'})
                if isinstance(value, str) and len(value) > 120:
                    raise ValidationError({'settings': f'{category}.{key} must be 120 characters or fewer.'})
                if isinstance(value, int) and not isinstance(value, bool) and value < 1:
                    raise ValidationError({'settings': f'{category}.{key} must be greater than zero.'})
                validated.append((category, key, value))

        with transaction.atomic():
            for category, key, value in validated:
                previous = settings[category][key]
                if previous == value:
                    continue
                SystemSetting.objects.update_or_create(
                    key=key,
                    defaults={'category': category, 'value': value, 'updated_by': request.user if request.user.is_authenticated else None},
                )
                SecurityAuditEvent.objects.create(
                    actor=request.user if request.user.is_authenticated else None,
                    action='settings.updated',
                    target_type='settings',
                    target_id=f'{category}.{key}',
                    details={'previous': previous, 'value': value},
                )
                settings[category][key] = value

    audit_log = [
        {
            'id': event.id,
            'actor_name': event.actor.get_full_name() or event.actor.get_username() if event.actor else 'System',
            'action': event.action,
            'target_id': event.target_id,
            'details': event.details,
            'created_at': event.created_at,
        }
        for event in SecurityAuditEvent.objects.filter(target_type='settings').select_related('actor')[:20]
    ]
    return Response({'settings': settings, 'audit_log': audit_log})


@api_view(['GET'])
@permission_classes([AllowAny])
def exchange_rates(request):
    cached_rates = cache.get('ugx_exchange_rates')
    if cached_rates is None:
        try:
            with urlopen('https://open.er-api.com/v6/latest/UGX', timeout=5) as response:
                payload = json.load(response)
        except (URLError, TimeoutError, OSError, ValueError):
            return Response({'detail': 'Live UGX exchange rates are temporarily unavailable.'}, status=503)

        raw_rates = payload.get('rates') if isinstance(payload, dict) and payload.get('result') == 'success' and payload.get('base_code') == 'UGX' else None
        updated_at = payload.get('time_last_update_utc') if isinstance(payload, dict) else None
        if not isinstance(raw_rates, dict) or not isinstance(updated_at, str):
            return Response({'detail': 'The exchange-rate service returned an invalid response.'}, status=502)

        rates = {
            code: rate
            for code, rate in raw_rates.items()
            if isinstance(code, str)
            and re.fullmatch(r'[A-Z]{3}', code)
            and isinstance(rate, (int, float))
            and not isinstance(rate, bool)
            and isfinite(rate)
            and rate > 0
        }
        rates['UGX'] = 1
        cached_rates = {'rates': rates, 'updated_at': updated_at}
        cache.set('ugx_exchange_rates', cached_rates, timeout=3600)

    configured_currency = SystemSetting.objects.filter(category='organization', key='currency').values_list('value', flat=True).first() or 'UGX'
    return Response({
        'base_currency': 'UGX',
        'currency': configured_currency,
        'rates': cached_rates['rates'],
        'updated_at': cached_rates['updated_at'],
    })


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
        purchases = supplier.purchases.select_related('supplier').prefetch_related('items__product').all()
        open_purchases = [purchase for purchase in purchases if purchase.status == Purchase.Status.ORDERED]
        received_purchases = [purchase for purchase in purchases if purchase.status == Purchase.Status.RECEIVED]
        return Response({
            'supplier': SupplierSerializer(supplier).data,
            'lifetime_spend': SupplierSerializer(supplier).data['lifetime_spend'],
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
            reference=data.get('reference', '').strip() or f'PAY-{uuid4().hex[:8].upper()}',
            note=data.get('note', '').strip() or 'Supplier payment issued',
        )
        return Response({
            'supplier': SupplierSerializer(supplier).data,
            'ledger_entry': SupplierLedgerEntrySerializer(entry).data,
        }, status=201)


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
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
                reference=reference,
                note=note,
            ))
        return Response({
            'customer': CustomerSerializer(customer).data,
            'ledger_entry': CustomerLedgerEntrySerializer(new_entries[0]).data,
            'ledger_entries': CustomerLedgerEntrySerializer(new_entries, many=True).data,
        }, status=201)


class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.all()
    serializer_class = ExpenseSerializer
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['expense_number', 'merchant', 'description', 'reference', 'category']
    ordering_fields = ['expense_date', 'total_amount', 'created_at']
    ordering = ['-expense_date', '-created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        category = self.request.query_params.get('category')
        status = self.request.query_params.get('status')
        payment_method = self.request.query_params.get('payment_method')
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if category:
            queryset = queryset.filter(category=category)
        if status and status != 'all':
            queryset = queryset.filter(status=status)
        if payment_method and payment_method != 'all':
            queryset = queryset.filter(payment_method=payment_method)
        if start_date:
            queryset = queryset.filter(expense_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(expense_date__lte=end_date)
        return queryset


class ExpenseBudgetViewSet(viewsets.ModelViewSet):
    queryset = ExpenseBudget.objects.all()
    serializer_class = ExpenseBudgetSerializer


class BalanceSheetAccountViewSet(viewsets.ModelViewSet):
    queryset = BalanceSheetAccount.objects.all()
    serializer_class = BalanceSheetAccountSerializer
    lookup_field = 'category'
    http_method_names = ['get', 'patch', 'head', 'options']


@api_view(['GET'])
def balance_sheet_summary(request):
    inventory_value = Product.objects.aggregate(
        total=Sum(F('quantity') * F('cost_price')),
    )['total'] or Decimal('0')
    receivables = Customer.objects.aggregate(total=Sum('outstanding_balance'))['total'] or Decimal('0')
    payables = Supplier.objects.aggregate(total=Sum('outstanding_balance'))['total'] or Decimal('0')
    unpaid_expenses = Expense.objects.filter(
        status=Expense.Status.APPROVED,
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')

    cents = Decimal('0.01')
    money = lambda amount: str(amount.quantize(cents))
    accounts = {
        account.category: account
        for account in BalanceSheetAccount.objects.all()
    }
    current_values = {
        BalanceSheetAccount.Category.ACCOUNTS_RECEIVABLE_NET: (
            receivables, 'Customer account balances', False, False,
        ),
        BalanceSheetAccount.Category.INVENTORIES: (
            inventory_value, 'Current inventory at cost', False, False,
        ),
        BalanceSheetAccount.Category.ACCOUNTS_PAYABLE: (
            payables, 'Supplier account balances', False, False,
        ),
        BalanceSheetAccount.Category.OTHER_CURRENT_LIABILITIES: (
            unpaid_expenses, 'Approved unpaid expenses plus other current balances', True, True,
        ),
    }
    categories = BalanceSheetAccount.Category

    def line(category):
        account = accounts.get(category)
        manual_amount = account.amount if account and account.amount is not None else Decimal('0')
        current_value, source, editable_current, include_manual = current_values.get(
            category,
            (account.amount if account else None, 'Manual balance', True, False),
        )
        if include_manual:
            current_value += manual_amount
        prior_amount = account.prior_amount if account else None
        current_complete = current_value is not None and (
            not include_manual or (account is not None and account.amount is not None)
        )
        return {
            'category': category,
            'name': account.get_category_display() if account else dict(categories.choices)[category],
            'current_amount': money(current_value) if current_value is not None else None,
            'manual_current_amount': money(account.amount) if account and account.amount is not None else None,
            'prior_amount': money(prior_amount) if prior_amount is not None else None,
            'source': source,
            'updated_at': account.updated_at.isoformat() if account else None,
            'editable_current': editable_current,
            'current_complete': current_complete,
            'prior_complete': prior_amount is not None,
        }

    group_definitions = {
        'assets': [
            ('Current assets', [
                categories.CASH_AND_CASH_EQUIVALENTS,
                categories.CURRENT_MARKETABLE_SECURITIES,
                categories.ACCOUNTS_RECEIVABLE_NET,
                categories.INVENTORIES,
                categories.VENDOR_NON_TRADE_RECEIVABLES,
                categories.OTHER_CURRENT_ASSETS,
            ]),
            ('Non-current assets', [
                categories.NONCURRENT_MARKETABLE_SECURITIES,
                categories.PROPERTY_PLANT_EQUIPMENT_NET,
                categories.OTHER_NONCURRENT_ASSETS,
            ]),
        ],
        'liabilities': [
            ('Current liabilities', [
                categories.ACCOUNTS_PAYABLE,
                categories.OTHER_CURRENT_LIABILITIES,
                categories.DEFERRED_REVENUE,
                categories.COMMERCIAL_PAPER,
                categories.CURRENT_TERM_DEBT,
            ]),
            ('Non-current liabilities', [
                categories.NONCURRENT_TERM_DEBT,
                categories.OTHER_NONCURRENT_LIABILITIES,
            ]),
        ],
        'equity': [
            ('Shareholders’ equity', [
                categories.COMMON_STOCK_AND_ADDITIONAL_PAID_IN_CAPITAL,
                categories.RETAINED_EARNINGS,
                categories.ACCUMULATED_OTHER_COMPREHENSIVE_INCOME_LOSS,
            ]),
        ],
    }

    def section(groups):
        result = []
        section_current = Decimal('0')
        section_prior = Decimal('0')
        section_current_complete = True
        section_prior_complete = True
        for title, group_categories in groups:
            rows = [line(category) for category in group_categories]
            group_current = sum((Decimal(row['current_amount'] or '0') for row in rows), Decimal('0')).quantize(cents)
            group_prior = sum((Decimal(row['prior_amount'] or '0') for row in rows), Decimal('0')).quantize(cents)
            group_current_complete = all(row['current_complete'] for row in rows)
            group_prior_complete = all(row['prior_complete'] for row in rows)
            section_current += group_current
            section_prior += group_prior
            section_current_complete = section_current_complete and group_current_complete
            section_prior_complete = section_prior_complete and group_prior_complete
            result.append({
                'title': title,
                'current_total': money(group_current),
                'prior_total': money(group_prior),
                'current_complete': group_current_complete,
                'prior_complete': group_prior_complete,
                'rows': rows,
            })
        return {
            'current_total': money(section_current),
            'prior_total': money(section_prior),
            'current_complete': section_current_complete,
            'prior_complete': section_prior_complete,
            'groups': result,
        }

    assets = section(group_definitions['assets'])
    liabilities = section(group_definitions['liabilities'])
    equity = section(group_definitions['equity'])
    total_assets = Decimal(assets['current_total'])
    total_liabilities = Decimal(liabilities['current_total'])
    total_equity = Decimal(equity['current_total'])
    difference = (total_assets - total_liabilities - total_equity).quantize(cents)
    prior_difference = (
        Decimal(assets['prior_total'])
        - Decimal(liabilities['prior_total'])
        - Decimal(equity['prior_total'])
    ).quantize(cents)
    current_complete = all(
        row['current_complete']
        for section in (assets, liabilities, equity)
        for group in section['groups']
        for row in group['rows']
    )
    prior_complete = all(
        row['prior_complete']
        for section in (assets, liabilities, equity)
        for group in section['groups']
        for row in group['rows']
    )
    return Response({
        'as_of_date': timezone.localdate().isoformat(),
        'current_year': timezone.localdate().year,
        'prior_year': timezone.localdate().year - 1,
        'assets': assets,
        'liabilities': liabilities,
        'equity': equity,
        'total_assets': money(total_assets),
        'total_liabilities': money(total_liabilities),
        'total_equity': money(total_equity),
        'difference': money(difference),
        'is_balanced': current_complete and difference == 0,
        'current_complete': current_complete,
        'prior_difference': money(prior_difference),
        'is_prior_balanced': prior_complete and prior_difference == 0,
        'prior_complete': prior_complete,
    })


def sync_notifications():
    active_keys = []

    def sync(source_key, **values):
        active_keys.append(source_key)
        notification, created = Notification.objects.get_or_create(
            source_key=source_key,
            defaults={**values, 'is_active': True},
        )
        if created:
            return
        became_active = not notification.is_active
        for field, value in values.items():
            setattr(notification, field, value)
        notification.is_active = True
        if became_active:
            notification.is_read = False
            notification.is_dismissed = False
            notification.created_at = timezone.now()
        notification.save()

    for product in Product.objects.select_related('supplier').filter(is_active=True).filter(Q(quantity=0) | Q(quantity__lte=F('reorder_level'))):
        if product.quantity == 0:
            state = 'depleted'
            severity = Notification.Severity.CRITICAL
            title = 'Out of stock'
            message = f'{product.name} ({product.sku}) has no units remaining.'
        else:
            state = 'low'
            severity = Notification.Severity.WARNING
            title = 'Low stock'
            message = f'{product.name} ({product.sku}) has {product.quantity} units; the reorder level is {product.reorder_level}.'
        sync(
            f'stock:{product.id}:{state}',
            category=Notification.Category.STOCK,
            severity=severity,
            title=title,
            message=message,
            target_label=product.sku,
            dashboard='inventory',
        )

    today = timezone.localdate()
    for purchase in Purchase.objects.select_related('supplier').filter(
        status=Purchase.Status.ORDERED,
        expected_delivery__lte=today + timedelta(days=2),
    ):
        overdue = purchase.expected_delivery < today
        sync(
            f'purchase:{purchase.id}:delivery',
            category=Notification.Category.PROCUREMENT,
            severity=Notification.Severity.WARNING if overdue else Notification.Severity.INFO,
            title='Purchase delivery overdue' if overdue else 'Purchase delivery due soon',
            message=f'{purchase.reference} from {purchase.supplier.name} was due {purchase.expected_delivery}.' if overdue else f'{purchase.reference} from {purchase.supplier.name} is due {purchase.expected_delivery}.',
            target_label=purchase.reference,
            dashboard='purchases',
        )

    for expense in Expense.objects.filter(status=Expense.Status.PENDING).order_by('-created_at')[:10]:
        sync(
            f'expense:{expense.id}:approval',
            category=Notification.Category.OPERATIONS,
            severity=Notification.Severity.WARNING,
            title='Expense awaiting approval',
            message=f'{expense.merchant}: {expense.description} ({expense.total_amount} UGX) is pending approval.',
            target_label=expense.expense_number,
            dashboard='expenses',
        )

    for customer in Customer.objects.filter(outstanding_balance__gt=0).order_by('-outstanding_balance')[:10]:
        sync(
            f'customer:{customer.id}:balance',
            category=Notification.Category.BILLING,
            severity=Notification.Severity.INFO,
            title='Customer balance outstanding',
            message=f'{customer.name} has an outstanding balance of {customer.outstanding_balance} UGX.',
            target_label=customer.customer_code,
            dashboard='customers',
        )

    generated_sources = Q(source_key__startswith='stock:') | Q(source_key__startswith='purchase:') | Q(source_key__startswith='expense:') | Q(source_key__startswith='customer:')
    Notification.objects.filter(generated_sources, is_active=True).exclude(source_key__in=active_keys).update(is_active=False)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer

    def get_queryset(self):
        sync_notifications()
        return Notification.objects.filter(is_active=True, is_dismissed=False)

    @action(detail=False, methods=['post'])
    def read_all(self, request):
        updated = self.get_queryset().filter(is_read=False).update(is_read=True)
        return Response({'updated': updated})

    @action(detail=True, methods=['post'])
    def read(self, request, pk=None):
        notification = self.get_object()
        notification.is_read = True
        notification.save(update_fields=['is_read', 'updated_at'])
        return Response(self.get_serializer(notification).data)

    @action(detail=True, methods=['post'])
    def dismiss(self, request, pk=None):
        notification = self.get_object()
        notification.is_dismissed = True
        notification.is_read = True
        notification.save(update_fields=['is_dismissed', 'is_read', 'updated_at'])
        return Response(status=204)


class StaffMemberViewSet(viewsets.ModelViewSet):
    queryset = StaffMember.objects.all()
    serializer_class = StaffMemberSerializer
    permission_classes = [RoleModelPermissions]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['employee_number', 'full_name', 'job_title', 'department', 'email']
    ordering_fields = ['full_name', 'department', 'hire_date', 'pay_rate']
    ordering = ['full_name']

    def perform_create(self, serializer):
        worker = serializer.save()
        SecurityAuditEvent.objects.create(
            actor=self.request.user,
            action='staff.created',
            target_type='staff_member',
            target_id=worker.employee_number,
            details={'full_name': worker.full_name, 'department': worker.department},
        )

    @transaction.atomic
    def perform_update(self, serializer):
        worker = serializer.save()
        compensation_fields = {'pay_basis', 'pay_rate', 'hours_per_period', 'withholding_percent', 'benefit_deduction'}
        if compensation_fields.intersection(serializer.validated_data):
            refresh_unpaid_worker_payroll(worker)
        SecurityAuditEvent.objects.create(
            actor=self.request.user,
            action='staff.updated',
            target_type='staff_member',
            target_id=worker.employee_number,
            details={'full_name': worker.full_name, 'updated_fields': sorted(serializer.validated_data.keys())},
        )


class StaffTaskViewSet(viewsets.ModelViewSet):
    queryset = StaffTask.objects.all()
    serializer_class = StaffTaskSerializer
    permission_classes = [RoleModelPermissions]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def perform_create(self, serializer):
        task = serializer.save()
        SecurityAuditEvent.objects.create(
            actor=self.request.user,
            action='staff.task_created',
            target_type='staff_task',
            target_id=str(task.id),
            details={
                'name': task.name,
                'pay_basis': task.pay_basis,
                'pay_rate': str(task.pay_rate),
                'target_tiers': task.target_tiers,
            },
        )

    @transaction.atomic
    def perform_update(self, serializer):
        updated_fields = set(serializer.validated_data)
        task = serializer.save()
        if not task.is_active:
            StaffTaskAssignment.objects.filter(task=task, is_active=True).update(is_active=False)
        if updated_fields.intersection({'name', 'pay_rate', 'target_tiers'}):
            payroll_periods = set(PayrollRun.objects.values_list('period', flat=True))
            entry_periods = StaffTaskEntry.objects.filter(task=task).dates('date', 'month')
            for month_start in entry_periods:
                period = month_start.strftime('%Y-%m')
                if period in payroll_periods:
                    continue
                StaffTaskEntry.objects.filter(
                    task=task,
                    date__year=month_start.year,
                    date__month=month_start.month,
                ).update(
                    task_name=task.name,
                    pay_rate=task.pay_rate,
                    target_tiers=task.target_tiers,
                )
        SecurityAuditEvent.objects.create(
            actor=self.request.user,
            action='staff.task_updated',
            target_type='staff_task',
            target_id=str(task.id),
            details={'name': task.name, 'updated_fields': sorted(serializer.validated_data.keys())},
        )


def record_permanent_task_entries(worker, work_date, attended, user):
    if not attended:
        StaffTaskEntry.objects.filter(
            worker=worker,
            date=work_date,
        ).delete()
        refresh_daily_attendance_wage(worker, work_date)
        return

    assignments = StaffTaskAssignment.objects.filter(
        worker=worker,
        is_active=True,
        assigned_from__lte=work_date,
        task__is_active=True,
    ).select_related('task')
    for assignment in assignments:
        task = assignment.task
        entry = StaffTaskEntry.objects.filter(worker=worker, task=task, date=work_date).first()
        if entry:
            if entry.assignment_type != StaffTaskEntry.AssignmentType.PERMANENT:
                entry.assignment_type = StaffTaskEntry.AssignmentType.PERMANENT
                entry.save(update_fields=['assignment_type'])
            continue
        StaffTaskEntry.objects.create(
            worker=worker,
            task=task,
            date=work_date,
            assignment_type=StaffTaskEntry.AssignmentType.PERMANENT,
            task_name=task.name,
            pay_basis=task.pay_basis,
            pay_rate=task.pay_rate,
            target_tiers=task.target_tiers,
            recorded_by=user,
        )
    refresh_daily_attendance_wage(worker, work_date)


class StaffTaskAssignmentViewSet(viewsets.ModelViewSet):
    queryset = StaffTaskAssignment.objects.select_related('worker', 'task')
    serializer_class = StaffTaskAssignmentSerializer
    permission_classes = [RoleModelPermissions]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get('active') == 'true':
            queryset = queryset.filter(is_active=True)
        return queryset

    def perform_create(self, serializer):
        assignment = serializer.save()
        attended_records = StaffAttendance.objects.filter(
            worker=assignment.worker,
            attended=True,
            date__gte=assignment.assigned_from,
            date__lte=timezone.localdate(),
        )
        for attendance in attended_records:
            if not PayrollRun.objects.filter(period=attendance.date.strftime('%Y-%m')).exists():
                record_permanent_task_entries(assignment.worker, attendance.date, True, self.request.user)
        SecurityAuditEvent.objects.create(
            actor=self.request.user,
            action='staff.task_assignment_created',
            target_type='staff_task_assignment',
            target_id=str(assignment.id),
            details={'worker': assignment.worker.full_name, 'task': assignment.task.name, 'assigned_from': assignment.assigned_from.isoformat()},
        )

    def perform_update(self, serializer):
        assignment = serializer.save()
        SecurityAuditEvent.objects.create(
            actor=self.request.user,
            action='staff.task_assignment_updated',
            target_type='staff_task_assignment',
            target_id=str(assignment.id),
            details={'worker': assignment.worker.full_name, 'task': assignment.task.name, 'is_active': assignment.is_active},
        )


class StaffTaskEntryViewSet(viewsets.ViewSet):
    permission_classes = [RoleModelPermissions]

    def list(self, request):
        period = request.query_params.get('period', '')
        try:
            parsed_period = datetime.strptime(period, '%Y-%m')
        except (TypeError, ValueError):
            raise ValidationError({'period': 'Enter a task work month in YYYY-MM format.'})
        if parsed_period.strftime('%Y-%m') != period:
            raise ValidationError({'period': 'Enter a task work month in YYYY-MM format.'})
        entries = StaffTaskEntry.objects.filter(
            date__year=parsed_period.year,
            date__month=parsed_period.month,
        ).select_related('worker', 'task')
        return Response(StaffTaskEntrySerializer(entries, many=True).data)

    @action(detail=False, methods=['post'])
    @transaction.atomic
    def remove_permanent(self, request):
        serializer = StaffTaskEntryRemovalInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        worker = serializer.validated_data['worker']
        task = serializer.validated_data['task']
        work_date = serializer.validated_data['date']
        if work_date > timezone.localdate():
            raise ValidationError({'date': 'Choose a task date that is not in the future.'})
        if PayrollRun.objects.filter(period=work_date.strftime('%Y-%m')).exists():
            raise ValidationError({'period': 'Task work is locked because payroll for this month has been generated.'})

        entry = StaffTaskEntry.objects.select_for_update().filter(
            worker=worker,
            task=task,
            date=work_date,
            assignment_type=StaffTaskEntry.AssignmentType.PERMANENT,
        ).first()
        if entry is None:
            raise ValidationError({'task': 'The permanent task record could not be found for this date.'})

        assignment = StaffTaskAssignment.objects.select_for_update().filter(
            worker=worker,
            task=task,
            is_active=True,
            assigned_from__lte=work_date,
        ).first()
        if assignment:
            assignment.is_active = False
            assignment.save(update_fields=['is_active'])
            SecurityAuditEvent.objects.create(
                actor=request.user,
                action='staff.task_assignment_updated',
                target_type='staff_task_assignment',
                target_id=str(assignment.id),
                details={
                    'worker': worker.full_name,
                    'task': task.name,
                    'is_active': False,
                    'removed_on': work_date.isoformat(),
                },
            )

        entry.delete()
        refresh_daily_attendance_wage(worker, work_date)
        SecurityAuditEvent.objects.create(
            actor=request.user,
            action='staff.task_work_removed',
            target_type='staff_task_entry',
            target_id=f'{worker.id}:{task.id}:{work_date.isoformat()}',
            details={
                'worker': worker.full_name,
                'task': task.name,
                'date': work_date.isoformat(),
                'permanent_assignment_deactivated': bool(assignment),
            },
        )
        return Response({'removed': True, 'permanent_assignment_deactivated': bool(assignment)})

    @action(detail=False, methods=['post'])
    @transaction.atomic
    def record_day(self, request):
        date_value = request.data.get('date', '')
        try:
            work_date = datetime.strptime(date_value, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            raise ValidationError({'date': 'Enter a task date in YYYY-MM-DD format.'})
        if work_date.isoformat() != date_value or work_date > timezone.localdate():
            raise ValidationError({'date': 'Choose a valid task date that is not in the future.'})
        if PayrollRun.objects.filter(period=work_date.strftime('%Y-%m')).exists():
            raise ValidationError({'period': 'Task work is locked because payroll for this month has been generated.'})

        rows = request.data.get('records')
        if not isinstance(rows, list):
            raise ValidationError({'records': 'Submit a list of task assignments.'})
        serializer = StaffTaskEntryInputSerializer(data=rows, many=True)
        serializer.is_valid(raise_exception=True)
        missing_target_units = {
            index: {'units_worked': 'Enter the number of units completed for this task.'}
            for index, (submitted, row) in enumerate(zip(rows, serializer.validated_data))
            if row['task'].pay_basis == StaffTask.PayBasis.TARGET
            and 'units_worked' not in submitted
        }
        if missing_target_units:
            raise ValidationError({'records': missing_target_units})
        keys = [(row['worker'].id, row['task'].id) for row in serializer.validated_data]
        if len(keys) != len(set(keys)):
            raise ValidationError({'records': 'A worker can only be assigned to each task once per day.'})

        existing_entries = {
            (entry.worker_id, entry.task_id): entry
            for entry in StaffTaskEntry.objects.filter(date=work_date)
        }
        saved_entries = []
        submitted_keys = set(keys)
        for row in serializer.validated_data:
            worker = row['worker']
            task = row['task']
            if worker.status != StaffMember.Status.ACTIVE:
                raise ValidationError({'worker': f'{worker.full_name} must be an active worker.'})
            if worker.hire_date > work_date:
                raise ValidationError({'worker': f'{worker.full_name} was not employed on this task date.'})
            if not StaffAttendance.objects.filter(worker=worker, date=work_date, attended=True).exists():
                raise ValidationError({'worker': f'{worker.full_name} must be marked attended before a task can be recorded.'})
            existing = existing_entries.get((worker.id, task.id))
            if not task.is_active and existing is None:
                raise ValidationError({'task': f'{task.name} is inactive and cannot receive new work assignments.'})
            if existing:
                existing.hours = row['hours']
                existing.units_worked = row['units_worked']
                existing.recorded_by = request.user
                existing.save(update_fields=['hours', 'units_worked', 'recorded_by'])
                saved_entries.append(existing)
            else:
                saved_entries.append(StaffTaskEntry.objects.create(
                    worker=worker,
                    task=task,
                    date=work_date,
                    task_name=task.name,
                    pay_basis=task.pay_basis,
                    pay_rate=task.pay_rate,
                    hours=row['hours'],
                    target_tiers=task.target_tiers,
                    units_worked=row['units_worked'],
                    recorded_by=request.user,
                ))
        for worker_id, task_id in existing_entries.keys() - submitted_keys:
            if existing_entries[(worker_id, task_id)].assignment_type == StaffTaskEntry.AssignmentType.PERMANENT:
                continue
            StaffTaskEntry.objects.filter(
                date=work_date,
                worker_id=worker_id,
                task_id=task_id,
            ).delete()

        affected_worker_ids = {worker_id for worker_id, _task_id in existing_entries}
        affected_worker_ids.update(row['worker'].id for row in serializer.validated_data)
        for worker in StaffMember.objects.filter(id__in=affected_worker_ids):
            refresh_daily_attendance_wage(worker, work_date)

        SecurityAuditEvent.objects.create(
            actor=request.user,
            action='staff.task_work_recorded',
            target_type='staff_task_entry',
            target_id=work_date.isoformat(),
            details={'assignments_recorded': len(saved_entries)},
        )
        return Response(StaffTaskEntrySerializer(saved_entries, many=True).data)


class StaffAttendanceViewSet(viewsets.ViewSet):
    permission_classes = [RoleModelPermissions]

    def list(self, request):
        period = request.query_params.get('period', '')
        if period:
            try:
                parsed_period = datetime.strptime(period, '%Y-%m')
            except (TypeError, ValueError):
                raise ValidationError({'period': 'Enter an attendance month in YYYY-MM format.'})
            if parsed_period.strftime('%Y-%m') != period:
                raise ValidationError({'period': 'Enter an attendance month in YYYY-MM format.'})
            records = StaffAttendance.objects.filter(date__year=parsed_period.year, date__month=parsed_period.month).select_related('worker')
            return Response(StaffAttendanceSerializer(records, many=True).data)

        date_value = request.query_params.get('date', '')
        try:
            attendance_date = datetime.strptime(date_value, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            raise ValidationError({'date': 'Enter an attendance date in YYYY-MM-DD format.'})
        if attendance_date.isoformat() != date_value:
            raise ValidationError({'date': 'Enter an attendance date in YYYY-MM-DD format.'})
        records = StaffAttendance.objects.filter(date=attendance_date).select_related('worker')
        return Response(StaffAttendanceSerializer(records, many=True).data)

    @action(detail=False, methods=['post'])
    @transaction.atomic
    def record_day(self, request):
        date_value = request.data.get('date', '')
        try:
            attendance_date = datetime.strptime(date_value, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            raise ValidationError({'date': 'Enter an attendance date in YYYY-MM-DD format.'})
        if attendance_date.isoformat() != date_value or attendance_date > timezone.localdate():
            raise ValidationError({'date': 'Choose a valid date that is not in the future.'})
        if PayrollRun.objects.filter(period=attendance_date.strftime('%Y-%m')).exists():
            raise ValidationError({'period': 'Attendance is locked because payroll for this month has been generated.'})
        records_data = request.data.get('records')
        if not isinstance(records_data, list) or not records_data:
            raise ValidationError({'records': 'Add at least one worker attendance record.'})
        serializer = StaffAttendanceInputSerializer(data=records_data, many=True)
        serializer.is_valid(raise_exception=True)
        worker_ids = [row['worker'].id for row in serializer.validated_data]
        if len(worker_ids) != len(set(worker_ids)):
            raise ValidationError({'records': 'A worker can only be recorded once per day.'})

        workers_by_id = {row['worker'].id: row['worker'] for row in serializer.validated_data}
        for worker in workers_by_id.values():
            if worker.status != StaffMember.Status.ACTIVE:
                raise ValidationError({'worker': f'{worker.full_name} must be an active worker.'})

        attendance_rows = []
        for row in serializer.validated_data:
            worker = row['worker']
            attended = row['attended']
            output_quantity = row['output_quantity']
            attendance_rows.append(StaffAttendance(
                worker=worker,
                date=attendance_date,
                attended=attended,
                output_quantity=output_quantity,
                daily_wage_override=row['daily_wage_override'],
                daily_wage=daily_attendance_wage(
                    attendance_date,
                    attended,
                    output_quantity,
                    row['daily_wage_override'],
                ) if worker.pay_basis == StaffMember.PayBasis.DAILY else Decimal('0.00'),
                recorded_by=request.user,
            ))

        if attendance_rows:
            StaffAttendance.objects.bulk_create(
                attendance_rows,
                update_conflicts=True,
                update_fields=[
                    'attended',
                    'output_quantity',
                    'daily_wage_override',
                    'daily_wage',
                    'recorded_by',
                    'updated_at',
                ],
                unique_fields=['worker', 'date'],
            )

        worker_ids = list(workers_by_id)
        attended_worker_ids = [
            row['worker'].id for row in serializer.validated_data if row['attended']
        ]
        absent_worker_ids = list(set(worker_ids) - set(attended_worker_ids))
        if absent_worker_ids:
            StaffTaskEntry.objects.filter(
                worker_id__in=absent_worker_ids,
                date=attendance_date,
            ).delete()

        existing_entries = {
            (entry.worker_id, entry.task_id): entry
            for entry in StaffTaskEntry.objects.filter(
                worker_id__in=attended_worker_ids,
                date=attendance_date,
            )
        }
        assignments = StaffTaskAssignment.objects.filter(
            worker_id__in=attended_worker_ids,
            is_active=True,
            assigned_from__lte=attendance_date,
            task__is_active=True,
        ).select_related('worker', 'task')
        entries_to_create = []
        entries_to_update = []
        for assignment in assignments:
            task = assignment.task
            key = (assignment.worker_id, task.id)
            existing = existing_entries.get(key)
            if existing:
                if existing.assignment_type != StaffTaskEntry.AssignmentType.PERMANENT:
                    existing.assignment_type = StaffTaskEntry.AssignmentType.PERMANENT
                    entries_to_update.append(existing)
                continue
            entries_to_create.append(StaffTaskEntry(
                worker=assignment.worker,
                task=task,
                date=attendance_date,
                assignment_type=StaffTaskEntry.AssignmentType.PERMANENT,
                task_name=task.name,
                pay_basis=task.pay_basis,
                pay_rate=task.pay_rate,
                target_tiers=task.target_tiers,
                recorded_by=request.user,
            ))

        if entries_to_update:
            StaffTaskEntry.objects.bulk_update(entries_to_update, ['assignment_type'])
        if entries_to_create:
            StaffTaskEntry.objects.bulk_create(entries_to_create)

        workers_with_task_entries = set(StaffTaskEntry.objects.filter(
            worker_id__in=worker_ids,
            date=attendance_date,
        ).values_list('worker_id', flat=True))
        saved_records = list(StaffAttendance.objects.filter(
            worker_id__in=worker_ids,
            date=attendance_date,
        ).select_related('worker'))
        for attendance in saved_records:
            if attendance.worker.pay_basis == StaffMember.PayBasis.DAILY:
                attendance.daily_wage = (
                    daily_attendance_wage(
                        attendance_date,
                        True,
                        attendance.output_quantity,
                        attendance.daily_wage_override,
                    )
                    if attendance.attended and attendance.worker_id not in workers_with_task_entries
                    else Decimal('0.00')
                )
        StaffAttendance.objects.bulk_update(saved_records, ['daily_wage'])

        SecurityAuditEvent.objects.create(
            actor=request.user,
            action='staff.attendance_recorded',
            target_type='staff_attendance',
            target_id=attendance_date.isoformat(),
            details={'workers_recorded': len(attendance_rows)},
        )
        return Response(StaffAttendanceSerializer(saved_records, many=True).data)


@api_view(['GET'])
@permission_classes([RoleModelPermissions])
def staff_dashboard(request):
    current_period = request.query_params.get('period') or timezone.localdate().strftime('%Y-%m')
    try:
        parsed_period = datetime.strptime(current_period, '%Y-%m')
    except (TypeError, ValueError):
        raise ValidationError({'period': 'Enter a payroll period in YYYY-MM format.'})
    if parsed_period.strftime('%Y-%m') != current_period:
        raise ValidationError({'period': 'Enter a payroll period in YYYY-MM format.'})
    workers = StaffMember.objects.all()
    active_workers = list(workers.filter(status=StaffMember.Status.ACTIVE))
    current_run = PayrollRun.objects.filter(period=current_period).prefetch_related('lines').first()
    cent = Decimal('0.01')
    attendance_totals = {
        row['worker_id']: {'days_worked': row['days_worked'], 'gross': row['gross'] or Decimal('0.00')}
        for row in StaffAttendance.objects.filter(date__year=parsed_period.year, date__month=parsed_period.month, attended=True)
        .values('worker_id')
        .annotate(days_worked=Count('id'), gross=Sum('daily_wage'))
    }
    task_entries = list(StaffTaskEntry.objects.filter(
        date__year=parsed_period.year,
        date__month=parsed_period.month,
    ).select_related('task').order_by('date', 'id'))
    period_task_pay = task_pay_totals(task_entries)

    def estimate(worker):
        if worker.pay_basis == StaffMember.PayBasis.DAILY:
            base_gross = attendance_totals.get(worker.id, {}).get('gross', Decimal('0.00'))
        else:
            base_gross = worker.pay_rate if worker.pay_basis == StaffMember.PayBasis.MONTHLY else worker.pay_rate * worker.hours_per_period
        task_pay = period_task_pay.get(worker.id, Decimal('0.00'))
        gross = (base_gross + task_pay).quantize(cent, rounding=ROUND_HALF_UP)
        withholding = (gross * worker.withholding_percent / Decimal('100')).quantize(cent, rounding=ROUND_HALF_UP)
        benefits = min(worker.benefit_deduction, gross) if worker.pay_basis == StaffMember.PayBasis.DAILY else worker.benefit_deduction
        return gross, withholding, benefits, gross - withholding - benefits, task_pay

    preview = [estimate(worker) for worker in active_workers]
    summary = {
        'current_period': current_period,
        'active_workers': len(active_workers),
        'on_leave_workers': workers.filter(status=StaffMember.Status.LEAVE).count(),
        'inactive_workers': workers.filter(status=StaffMember.Status.INACTIVE).count(),
        'gross_total': current_run.gross_total if current_run else sum((row[0] for row in preview), Decimal('0')),
        'task_pay_total': (
            sum((line.task_pay for line in current_run.lines.all()), Decimal('0'))
            if current_run
            else sum((row[4] for row in preview), Decimal('0'))
        ),
        'withholding_total': current_run.withholding_total if current_run else sum((row[1] for row in preview), Decimal('0')),
        'benefits_total': current_run.benefits_total if current_run else sum((row[2] for row in preview), Decimal('0')),
        'net_total': current_run.net_total if current_run else sum((row[3] for row in preview), Decimal('0')),
        'run_status': current_run.status if current_run else 'draft',
        'run_id': current_run.id if current_run else None,
        'run_count': PayrollRun.objects.count(),
    }
    departments = []
    for department in sorted({worker.department for worker in active_workers}):
        members = [worker for worker in active_workers if worker.department == department]
        total = sum((estimate(worker)[0] for worker in members), Decimal('0'))
        departments.append({'name': department, 'workers': len(members), 'gross_total': total})

    return Response({
        'summary': summary,
        'workers': StaffMemberSerializer(
            workers,
            many=True,
            context={'attendance_totals': attendance_totals, 'task_pay_totals': period_task_pay},
        ).data,
        'departments': departments,
        'payroll_runs': PayrollRunSerializer(PayrollRun.objects.prefetch_related('lines')[:12], many=True).data,
    })


class PayrollRunViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PayrollRun.objects.prefetch_related('lines').all()
    serializer_class = PayrollRunSerializer
    permission_classes = [RoleModelPermissions]

    @action(detail=False, methods=['post'])
    @transaction.atomic
    def generate(self, request):
        period = request.data.get('period', '')
        try:
            parsed_period = datetime.strptime(period, '%Y-%m')
        except (TypeError, ValueError):
            raise ValidationError({'period': 'Enter a payroll period in YYYY-MM format.'})
        if parsed_period.strftime('%Y-%m') != period:
            raise ValidationError({'period': 'Enter a payroll period in YYYY-MM format.'})
        if PayrollRun.objects.filter(period=period).exists():
            raise ValidationError({'period': 'A payroll run already exists for this period.'})

        workers = list(StaffMember.objects.select_for_update().filter(status=StaffMember.Status.ACTIVE).order_by('id'))
        if not workers:
            raise ValidationError({'workers': 'Add at least one active worker before generating payroll.'})

        cent = Decimal('0.01')
        attendance_totals = {
            row['worker_id']: {'days_worked': row['days_worked'], 'gross': row['gross'] or Decimal('0.00')}
            for row in StaffAttendance.objects.filter(date__year=parsed_period.year, date__month=parsed_period.month, attended=True)
            .values('worker_id')
            .annotate(days_worked=Count('id'), gross=Sum('daily_wage'))
        }
        task_entries = list(StaffTaskEntry.objects.filter(
            date__year=parsed_period.year,
            date__month=parsed_period.month,
        ).select_related('task').order_by('date', 'id'))
        task_pay_by_worker = task_pay_totals(task_entries)
        run = PayrollRun.objects.create(period=period, worker_count=len(workers), created_by=request.user)
        lines = []
        for worker in workers:
            hours = worker.hours_per_period if worker.pay_basis == StaffMember.PayBasis.HOURLY else Decimal('0')
            days_worked = attendance_totals.get(worker.id, {}).get('days_worked', 0)
            if worker.pay_basis == StaffMember.PayBasis.DAILY:
                base_gross = attendance_totals.get(worker.id, {}).get('gross', Decimal('0.00'))
            else:
                base_gross = worker.pay_rate if worker.pay_basis == StaffMember.PayBasis.MONTHLY else worker.pay_rate * hours
            task_pay = task_pay_by_worker.get(worker.id, Decimal('0.00'))
            gross = (base_gross + task_pay).quantize(cent, rounding=ROUND_HALF_UP)
            withholding = (gross * worker.withholding_percent / Decimal('100')).quantize(cent, rounding=ROUND_HALF_UP)
            benefits = min(worker.benefit_deduction, gross) if worker.pay_basis == StaffMember.PayBasis.DAILY else worker.benefit_deduction
            if withholding + benefits > gross:
                raise ValidationError({'worker': f'Deductions exceed gross pay for {worker.employee_number}.'})
            lines.append(PayrollLine(
                run=run,
                worker=worker,
                employee_number=worker.employee_number,
                worker_name=worker.full_name,
                job_title=worker.job_title,
                department=worker.department,
                pay_basis=worker.pay_basis,
                hours=hours,
                days_worked=days_worked,
                task_pay=task_pay,
                gross_pay=gross,
                withholding=withholding,
                benefits=benefits,
                net_pay=gross - withholding - benefits,
            ))
        PayrollLine.objects.bulk_create(lines)
        run.gross_total = sum((line.gross_pay for line in lines), Decimal('0'))
        run.withholding_total = sum((line.withholding for line in lines), Decimal('0'))
        run.benefits_total = sum((line.benefits for line in lines), Decimal('0'))
        run.net_total = sum((line.net_pay for line in lines), Decimal('0'))
        run.save(update_fields=['gross_total', 'withholding_total', 'benefits_total', 'net_total'])
        SecurityAuditEvent.objects.create(
            actor=request.user,
            action='payroll.generated',
            target_type='payroll_run',
            target_id=period,
            details={'worker_count': run.worker_count, 'gross_total': str(run.gross_total), 'net_total': str(run.net_total)},
        )
        return Response(PayrollRunSerializer(run).data, status=201)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def mark_paid(self, request, pk=None):
        run = PayrollRun.objects.select_for_update().get(pk=pk)
        if run.status == PayrollRun.Status.PAID:
            raise ValidationError({'status': 'This payroll run is already marked paid.'})
        run.status = PayrollRun.Status.PAID
        run.paid_at = timezone.now()
        run.save(update_fields=['status', 'paid_at'])
        SecurityAuditEvent.objects.create(
            actor=request.user,
            action='payroll.marked_paid',
            target_type='payroll_run',
            target_id=run.period,
            details={'net_total': str(run.net_total)},
        )
        return Response(PayrollRunSerializer(run).data)


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
            Purchase.objects.select_related('supplier').prefetch_related('items__product')[:8],
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


@api_view(['GET'])
def expenses_summary(request):
    month_value = request.query_params.get('month')
    if month_value:
        try:
            start = datetime.strptime(month_value, '%Y-%m').date().replace(day=1)
        except ValueError:
            raise ValidationError({'month': 'Use YYYY-MM for the report month.'})
    else:
        start = timezone.localdate().replace(day=1)
    next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    end = next_month - timedelta(days=1)
    expense_records = Expense.objects.filter(expense_date__gte=start, expense_date__lte=end)
    expenses = expense_records.exclude(status=Expense.Status.REJECTED)
    totals = expenses.aggregate(total=Sum('total_amount'))
    pending = expenses.filter(status=Expense.Status.PENDING).aggregate(total=Sum('total_amount'))
    tax_reclaimable = expenses.filter(receipt_verified=True).aggregate(total=Sum('tax_amount'))
    money = lambda value: str((value or Decimal('0')).quantize(Decimal('0.01')))
    categories = list(expenses.values('category').annotate(
        total=Sum('total_amount'),
        count=Count('id'),
    ).order_by('-total'))
    budget_rows = []
    for budget in ExpenseBudget.objects.all():
        spend = expenses.filter(category=budget.category).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
        budget_rows.append({
            'id': budget.id,
            'category': budget.category,
            'cost_center': budget.cost_center,
            'manager': budget.manager,
            'monthly_limit': money(budget.monthly_limit),
            'spent': money(spend),
            'percent_used': round(float(spend / budget.monthly_limit * 100), 1) if budget.monthly_limit else 0,
        })
    largest = categories[0] if categories else None
    daily_by_type = {}
    for row in expenses.values('expense_date', 'expense_type').annotate(total=Sum('total_amount')):
        daily_by_type.setdefault(row['expense_date'], {})[row['expense_type']] = row['total']
    series = []
    cursor = start
    while cursor <= end:
        type_totals = daily_by_type.get(cursor, {})
        series.append({
            'label': f'{cursor.strftime("%b")} {cursor.day}',
            'total': float(sum(type_totals.values(), Decimal('0'))),
            'operational': float(type_totals.get(Expense.ExpenseType.OPERATIONAL, Decimal('0'))),
            'freight': float(type_totals.get(Expense.ExpenseType.FREIGHT, Decimal('0'))),
            'capital': float(type_totals.get(Expense.ExpenseType.CAPITAL, Decimal('0'))),
        })
        cursor += timedelta(days=1)
    return Response({
        'month': start.strftime('%Y-%m'),
        'start_date': start.isoformat(),
        'end_date': end.isoformat(),
        'total_expenses': money(totals['total']),
        'pending_approval': money(pending['total']),
        'pending_count': expenses.filter(status=Expense.Status.PENDING).count(),
        'tax_reclaimable': money(tax_reclaimable['total']),
        'verified_receipts': expenses.filter(receipt_verified=True).count(),
        'expense_count': expenses.count(),
        'largest_category': {
            'name': largest['category'],
            'total': money(largest['total']),
            'percent': round(float(largest['total'] / (totals['total'] or Decimal('1')) * 100), 1),
        } if largest else None,
        'categories': [{
            'name': row['category'],
            'total': money(row['total']),
            'count': row['count'],
            'percent': round(float(row['total'] / (totals['total'] or Decimal('1')) * 100), 1),
        } for row in categories],
        'budgets': budget_rows,
        'daily_series': series,
        'expenses': ExpenseSerializer(expense_records, many=True).data,
    })


@api_view(['POST'])
@transaction.atomic
def expenses_bulk_upload(request):
    rows = request.data.get('expenses')
    if not isinstance(rows, list) or not rows:
        raise ValidationError({'expenses': 'Provide a non-empty list of expense records.'})
    serializer = ExpenseSerializer(data=rows, many=True)
    serializer.is_valid(raise_exception=True)
    created = serializer.save()
    return Response(ExpenseSerializer(created, many=True).data, status=201)


@api_view(['GET'])
def dashboard_summary(request):
    products = Product.objects.select_related('category', 'supplier').filter(is_active=True)
    summary_products = ProductSerializer(products.order_by('quantity')[:8], many=True).data
    product_totals = products.aggregate(
        total_skus=Count('id'),
        total_units=Sum('quantity'),
        inventory_value=Sum(F('quantity') * F('cost_price')),
        low_stock_count=Count('id', filter=Q(quantity__gt=0, quantity__lte=F('reorder_level'))),
        out_of_stock_count=Count('id', filter=Q(quantity=0)),
    )
    today = timezone.localdate()
    days = 30 if request.query_params.get('range') == '30d' else 7
    start = today - timedelta(days=days - 1)
    start_at, end_at = day_range(start, today)
    sales_in_period = Sale.objects.filter(created_at__gte=start_at, created_at__lt=end_at)
    sale_revenue_by_date = {
        row['day']: row['revenue'] or Decimal('0')
        for row in sales_in_period.annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(revenue=Sum(F('subtotal') - F('discount_amount')))
    }
    sale_cost_expression = ExpressionWrapper(
        F('quantity') * F('unit_cost'),
        output_field=DecimalField(max_digits=24, decimal_places=2),
    )
    sale_cost_by_date = {
        row['day']: row['cost'] or Decimal('0')
        for row in SaleItem.objects.filter(
            sale__created_at__gte=start_at,
            sale__created_at__lt=end_at,
        )
        .annotate(day=TruncDate('sale__created_at'))
        .values('day')
        .annotate(cost=Sum(sale_cost_expression))
    }

    sale_receipts = sales_in_period.values('receipt_number')
    movement_amount_field = DecimalField(max_digits=24, decimal_places=2)
    movement_queryset = StockMovement.objects.select_related('product', 'product__supplier')
    movement_summaries = (
        StockMovement.objects.filter(
            created_at__gte=start_at,
            created_at__lt=end_at,
            movement_type__in=[StockMovement.MovementType.INBOUND, StockMovement.MovementType.OUTBOUND],
        )
        .exclude(Q(movement_type=StockMovement.MovementType.OUTBOUND, reference__in=sale_receipts))
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(
            purchases=Sum(Case(
                When(
                    movement_type=StockMovement.MovementType.INBOUND,
                    then=ExpressionWrapper(
                        Abs(F('quantity')) * F('product__cost_price'),
                        output_field=movement_amount_field,
                    ),
                ),
                default=Value(Decimal('0.00'), output_field=movement_amount_field),
                output_field=movement_amount_field,
            )),
            legacy_sales=Sum(Case(
                When(
                    movement_type=StockMovement.MovementType.OUTBOUND,
                    then=ExpressionWrapper(
                        Abs(F('quantity')) * F('product__unit_price'),
                        output_field=movement_amount_field,
                    ),
                ),
                default=Value(Decimal('0.00'), output_field=movement_amount_field),
                output_field=movement_amount_field,
            )),
            legacy_sales_cost=Sum(Case(
                When(
                    movement_type=StockMovement.MovementType.OUTBOUND,
                    then=ExpressionWrapper(
                        Abs(F('quantity')) * F('product__cost_price'),
                        output_field=movement_amount_field,
                    ),
                ),
                default=Value(Decimal('0.00'), output_field=movement_amount_field),
                output_field=movement_amount_field,
            )),
        )
    )
    legacy_sales_by_date = {}
    purchases_by_date = {}
    legacy_sales_total = Decimal('0')
    legacy_sales_cost = Decimal('0')
    purchases = Decimal('0')
    today_purchases = Decimal('0')
    for row in movement_summaries:
        movement_date = row['day']
        day_purchases = row['purchases'] or Decimal('0')
        legacy_revenue = row['legacy_sales'] or Decimal('0')
        legacy_cost = row['legacy_sales_cost'] or Decimal('0')
        if day_purchases:
            purchases += day_purchases
            purchases_by_date[movement_date] = day_purchases
            if movement_date == today:
                today_purchases += day_purchases
        if legacy_revenue:
            legacy_sales_by_date[movement_date] = legacy_revenue
            legacy_sales_total += legacy_revenue
            legacy_sales_cost += legacy_cost

    sales = sum(sale_revenue_by_date.values(), Decimal('0')) + legacy_sales_total
    today_sales = sale_revenue_by_date.get(today, Decimal('0')) + legacy_sales_by_date.get(today, Decimal('0'))
    period_cost = sum(sale_cost_by_date.values(), Decimal('0')) + legacy_sales_cost
    category_rows = [
        {
            'id': row['category_id'],
            'name': row['category__name'],
            'units': row['units'],
            'value': str(row['value'] or Decimal('0')),
        }
        for row in products.values('category_id', 'category__name')
        .annotate(units=Sum('quantity'), value=Sum(F('quantity') * F('cost_price')))
        .filter(units__gt=0)
        .order_by('-units')
    ]
    total_category_units = sum(item['units'] for item in category_rows) or 1
    for row in category_rows:
        row['percent'] = round(row['units'] * 100 / total_category_units)
    series = []
    for offset in range(days):
        date = start + timedelta(days=offset)
        series.append({
            'label': f'{date.strftime("%b")} {date.day}',
            'sales': float(sale_revenue_by_date.get(date, Decimal('0')) + legacy_sales_by_date.get(date, Decimal('0'))),
            'purchases': float(purchases_by_date.get(date, Decimal('0'))),
        })
    gross_profit = sales - period_cost
    gross_margin = round(float(gross_profit / sales * 100), 1) if sales else 0
    recent_movements = StockMovementSerializer(movement_queryset[:12], many=True).data
    return Response({
        'total_skus': product_totals['total_skus'],
        'total_units': product_totals['total_units'] or 0,
        'inventory_value': str(product_totals['inventory_value'] or Decimal('0')),
        'low_stock_count': product_totals['low_stock_count'],
        'out_of_stock_count': product_totals['out_of_stock_count'],
        'today_sales': str(today_sales),
        'today_purchases': str(today_purchases),
        'gross_profit': str(gross_profit),
        'gross_margin': gross_margin,
        'period_sales': str(sales),
        'period_purchases': str(purchases),
        'products': summary_products,
        'recent_movements': recent_movements,
        'categories': category_rows,
        'series': series,
    })

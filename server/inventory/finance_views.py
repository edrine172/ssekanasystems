from decimal import Decimal
from django.db.models import F, Sum
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import BalanceSheetAccount, Customer, Expense, Product, Supplier
from .serializers import BalanceSheetAccountSerializer


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

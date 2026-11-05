from datetime import datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from .models import Expense, ExpenseBudget, ExpenseCategory, ExpenseTypeOption
from .permissions import RoleModelPermissions
from .serializers import (
    ExpenseBudgetSerializer,
    ExpenseCategorySerializer,
    ExpenseSerializer,
    ExpenseTypeOptionSerializer,
)


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
        status_filter = self.request.query_params.get('status')
        payment_method = self.request.query_params.get('payment_method')
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if category:
            queryset = queryset.filter(category=category)
        if status_filter and status_filter != 'all':
            queryset = queryset.filter(status=status_filter)
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


def _expense_options_response(response_status=None):
    data = {
        'categories': ExpenseCategorySerializer(ExpenseCategory.objects.all(), many=True).data,
        'types': ExpenseTypeOptionSerializer(ExpenseTypeOption.objects.all(), many=True).data,
    }
    return Response(data, status=response_status) if response_status else Response(data)


@api_view(['GET', 'POST'])
@permission_classes([RoleModelPermissions])
def expense_options(request):
    if request.method == 'GET':
        return _expense_options_response()

    kind = request.data.get('kind')
    if kind == 'category':
        serializer = ExpenseCategorySerializer(data={'name': request.data.get('name', '')})
    elif kind == 'type':
        serializer = ExpenseTypeOptionSerializer(data={'label': request.data.get('name', '')})
    else:
        raise ValidationError({'kind': 'Choose category or type.'})
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return _expense_options_response(status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([RoleModelPermissions])
def delete_expense_category(request, category_id):
    category = get_object_or_404(ExpenseCategory, pk=category_id)
    category.delete()
    return _expense_options_response()


@api_view(['DELETE'])
@permission_classes([RoleModelPermissions])
def delete_expense_type(request, type_id):
    expense_type = get_object_or_404(ExpenseTypeOption, pk=type_id)
    expense_type.delete()
    return _expense_options_response()


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
            'types': {value: float(amount) for value, amount in type_totals.items()},
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
        'expense_types': ExpenseTypeOptionSerializer(ExpenseTypeOption.objects.all(), many=True).data,
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

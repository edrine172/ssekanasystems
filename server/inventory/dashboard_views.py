from datetime import timedelta
from decimal import Decimal
from django.db.models import Case, Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value, When
from django.db.models.functions import Abs, TruncDate
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Product, Sale, SaleItem, StockMovement
from .serializers import ProductSerializer, StockMovementSerializer
from .date_ranges import day_range


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

from datetime import timedelta
from django.db.models import F, Q
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Customer, Expense, Notification, Product, Purchase
from .serializers import NotificationSerializer


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

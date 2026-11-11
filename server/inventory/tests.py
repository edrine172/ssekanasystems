import json
import gzip
from io import BytesIO
from decimal import Decimal
from datetime import timedelta
from urllib.error import URLError
from unittest.mock import patch
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.contrib.sessions.models import Session
from django.core import serializers
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import QuerySet
from django.test import Client
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import BalanceSheetAccount, BottleCustomerPO, BottleDelivery, BottleProduct, ClientMaterial, ClientMaterialPO, ClientMaterialReceipt, Category, Customer, CustomerLedgerEntry, Expense, ExpenseBudget, ExpenseCategory, ExpenseTypeOption, Notification, PayrollLine, PayrollRun, Product, Purchase, PurchaseItem, Sale, SaleItem, SecurityAuditEvent, StaffAttendance, StaffMember, StaffTask, StaffTaskEntry, StockMovement, Supplier, SupplierLedgerEntry, SystemSetting


class AdminAPITestCase(APITestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username='dashboard-admin',
            password='test-password',
        )
        self.client.force_authenticate(user=self.admin)


class CategoryManagementTests(AdminAPITestCase):
    def test_category_can_be_created_and_deleted_when_unused(self):
        created = self.client.post('/api/categories/', {
            'name': 'Office supplies',
            'description': '',
        }, format='json')

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data['name'], 'Office supplies')

        deleted = self.client.delete(f"/api/categories/{created.data['id']}/")
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(Category.objects.filter(name='Office supplies').exists())

    def test_category_in_use_cannot_be_deleted(self):
        category = Category.objects.create(name='Product category')
        Product.objects.create(
            sku='CAT-001',
            name='Categorized product',
            category=category,
            unit_price='1.00',
        )

        response = self.client.delete(f'/api/categories/{category.id}/')

        self.assertEqual(response.status_code, 400)
        self.assertIn('assigned to products', response.data['detail'])
        self.assertTrue(Category.objects.filter(pk=category.id).exists())


class DatabaseBackupTests(AdminAPITestCase):
    def test_superuser_can_download_compressed_database_fixture(self):
        category = Category.objects.create(name='Backup category')
        Product.objects.create(
            sku='BACKUP-001',
            name='Backup product',
            category=category,
            unit_price='12.50',
        )
        SystemSetting.objects.create(
            key='backup_test_business_name',
            value='Backup Test Business',
            category='organization',
        )

        original_iterator = QuerySet.iterator
        chunk_sizes = []

        def capture_chunk_size(queryset, *args, **kwargs):
            chunk_sizes.append(kwargs.get('chunk_size'))
            yield from original_iterator(queryset, *args, **kwargs)

        with patch.object(QuerySet, 'iterator', capture_chunk_size):
            response = self.client.get('/api/system/backup/')

        self.assertEqual(response.status_code, 200)
        self.assertIn(100, chunk_sizes)
        self.assertEqual(response['Content-Type'], 'application/gzip')
        self.assertIn('attachment; filename="stockpulse-database-backup-', response['Content-Disposition'])
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
        compressed_fixture = b''.join(response.streaming_content)
        self.assertEqual(compressed_fixture[8], 4)
        fixture_text = gzip.decompress(compressed_fixture)
        self.assertNotIn(b'\n  {', fixture_text)
        fixture = json.loads(fixture_text)
        self.assertTrue(any(
            row['model'] == 'inventory.product'
            and row['fields']['sku'] == 'BACKUP-001'
            for row in fixture
        ))
        self.assertTrue(any(
            row['model'] == 'inventory.systemsetting'
            and row['fields']['key'] == 'backup_test_business_name'
            and row['fields']['value'] == 'Backup Test Business'
            for row in fixture
        ))
        self.assertFalse(any(row['model'] == 'sessions.session' for row in fixture))

    def test_non_superusers_cannot_download_database_backup(self):
        regular_admin = get_user_model().objects.create_user(
            username='regular-backup-admin',
            password='test-password',
            is_staff=True,
        )
        self.client.force_authenticate(user=regular_admin)

        response = self.client.get('/api/system/backup/')

        self.assertEqual(response.status_code, 403)

    def test_anonymous_users_cannot_download_database_backup(self):
        self.client.force_authenticate(user=None)

        response = self.client.get('/api/system/backup/')

        self.assertEqual(response.status_code, 403)

    def test_restore_replaces_database_and_returns_pre_restore_safety_backup(self):
        existing_category = Category.objects.create(name='Pre-restore category')
        restored_category = Category.objects.create(name='Restored category')
        fixture = serializers.serialize('json', [self.admin, restored_category]).encode('utf-8')
        upload = SimpleUploadedFile('stockpulse-database-backup.json', fixture, content_type='application/json')

        response = self.client.post('/api/system/backup/restore/', {'backup': upload}, format='multipart')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/gzip')
        self.assertIn('stockpulse-pre-restore-safety-backup-', response['Content-Disposition'])
        restored_fixture = json.loads(gzip.decompress(b''.join(response.streaming_content)))
        self.assertTrue(any(
            row['model'] == 'inventory.category'
            and row['fields']['name'] == existing_category.name
            for row in restored_fixture
        ))
        self.assertEqual(response['X-Restored-Record-Count'], '2')
        self.assertFalse(Category.objects.filter(name=existing_category.name).exists())
        self.assertTrue(Category.objects.filter(name=restored_category.name).exists())

    def test_compressed_backup_can_be_restored_and_returns_private_safety_copy(self):
        existing_category = Category.objects.create(name='Compressed backup pre-restore')
        restored_category = Category.objects.create(name='Compressed backup restored')
        fixture = serializers.serialize('json', [self.admin, restored_category]).encode('utf-8')
        upload = SimpleUploadedFile(
            'stockpulse-database-backup.json.gz',
            gzip.compress(fixture),
            content_type='application/gzip',
        )

        response = self.client.post('/api/system/backup/restore/', {'backup': upload}, format='multipart')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
        self.assertEqual(response['Pragma'], 'no-cache')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        safety_fixture = json.loads(gzip.decompress(b''.join(response.streaming_content)))
        self.assertEqual(response['X-Restored-Record-Count'], '2')
        self.assertTrue(any(
            row['model'] == 'inventory.category'
            and row['fields']['name'] == existing_category.name
            for row in safety_fixture
        ))
        self.assertFalse(Category.objects.filter(name=existing_category.name).exists())
        self.assertTrue(Category.objects.filter(name=restored_category.name).exists())

    def test_failed_restore_rolls_back_database_changes(self):
        existing_category = Category.objects.create(name='Must remain after failed restore')
        fixture = json.dumps([{
            'model': 'inventory.product',
            'pk': 991,
            'fields': {
                'sku': 'RESTORE-INVALID',
                'name': 'Invalid restored product',
                'category': 999999,
                'supplier': None,
                'quantity': 1,
                'reorder_level': 0,
                'is_active': True,
                'unit_price': '1.00',
                'cost_price': '0.00',
                'location': '',
                'updated_at': '2026-01-01T00:00:00Z',
                'created_at': '2026-01-01T00:00:00Z',
            },
        }]).encode('utf-8')
        upload = SimpleUploadedFile('invalid-backup.json', fixture, content_type='application/json')

        response = self.client.post('/api/system/backup/restore/', {'backup': upload}, format='multipart')

        self.assertEqual(response.status_code, 400)
        self.assertTrue(Category.objects.filter(pk=existing_category.pk).exists())

    def test_non_superusers_cannot_restore_database_backup(self):
        regular_admin = get_user_model().objects.create_user(
            username='regular-backup-restore-admin',
            password='test-password',
            is_staff=True,
        )
        self.client.force_authenticate(user=regular_admin)
        upload = SimpleUploadedFile('backup.json', b'[]', content_type='application/json')

        response = self.client.post('/api/system/backup/restore/', {'backup': upload}, format='multipart')

        self.assertEqual(response.status_code, 403)

    def test_restore_rejects_backup_without_active_superuser(self):
        existing_category = Category.objects.create(name='Must remain without admin backup')
        fixture = serializers.serialize('json', [existing_category]).encode('utf-8')
        upload = SimpleUploadedFile('backup-without-admin.json', fixture, content_type='application/json')

        response = self.client.post('/api/system/backup/restore/', {'backup': upload}, format='multipart')

        self.assertEqual(response.status_code, 400)
        self.assertTrue(Category.objects.filter(pk=existing_category.pk).exists())


class ProductAvailabilityTests(AdminAPITestCase):
    def setUp(self):
        super().setUp()
        category = Category.objects.create(name='Product availability')
        self.product = Product.objects.create(
            sku='AVAIL-001',
            name='Availability product',
            category=category,
            quantity=5,
            reorder_level=1,
            unit_price='12.00',
            cost_price='7.00',
        )

    def test_products_can_be_deactivated_and_reactivated(self):
        self.assertTrue(self.client.get('/api/products/').data[0]['is_active'])

        deactivated = self.client.patch(
            f'/api/products/{self.product.id}/',
            {'is_active': False},
            format='json',
        )

        self.assertEqual(deactivated.status_code, 200)
        self.assertFalse(deactivated.data['is_active'])
        self.assertEqual(self.client.get('/api/products/?active=true').data, [])
        self.assertFalse(self.client.get('/api/products/?active=false').data[0]['is_active'])

        reactivated = self.client.patch(
            f'/api/products/{self.product.id}/',
            {'is_active': True},
            format='json',
        )

        self.assertEqual(reactivated.status_code, 200)
        self.assertTrue(reactivated.data['is_active'])

    def test_deactivated_products_cannot_be_sold(self):
        self.product.is_active = False
        self.product.save(update_fields=['is_active'])

        response = self.client.post('/api/sales/checkout/', {
            'payment_method': 'cash',
            'items': [{'product': self.product.id, 'quantity': 1}],
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Sale.objects.exists())

    def test_deactivated_products_cannot_be_added_to_new_purchase_orders(self):
        supplier = Supplier.objects.create(name='Availability supplier')
        self.product.is_active = False
        self.product.save(update_fields=['is_active'])

        response = self.client.post('/api/purchases/', {
            'supplier': supplier.id,
            'items': [{'product': self.product.id, 'quantity': 2, 'unit_cost': '7.00'}],
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Purchase.objects.exists())

    def test_products_can_be_deleted_without_history_but_history_is_preserved(self):
        unused = Product.objects.create(
            sku='AVAIL-002',
            name='Unused product',
            category=self.product.category,
            unit_price='1.00',
        )
        self.assertEqual(self.client.delete(f'/api/products/{unused.id}/').status_code, 204)

        sale = Sale.objects.create(
            receipt_number='SALE-AVAIL-001',
            customer_name='Walk-in Customer',
            payment_method=Sale.PaymentMethod.CASH,
            subtotal='12.00',
            total='12.00',
        )
        SaleItem.objects.create(
            sale=sale,
            product=self.product,
            product_name=self.product.name,
            product_sku=self.product.sku,
            quantity=1,
            unit_price='12.00',
            unit_cost='7.00',
        )

        response = self.client.delete(f'/api/products/{self.product.id}/')

        self.assertEqual(response.status_code, 409)
        self.assertIn('Deactivate it instead', response.data['detail'])
        self.assertTrue(Product.objects.filter(pk=self.product.id).exists())
        self.assertTrue(SaleItem.objects.filter(product=self.product).exists())


class NotificationTests(AdminAPITestCase):
    def setUp(self):
        super().setUp()
        category = Category.objects.create(name='Notification inventory')
        self.product = Product.objects.create(
            sku='ALERT-001', name='Alert product', category=category,
            quantity=0, reorder_level=5, unit_price='12.00', cost_price='8.00',
        )

    def test_notifications_sync_stock_state_and_support_read_and_dismiss(self):
        response = self.client.get('/api/notifications/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['category'], Notification.Category.STOCK)
        self.assertEqual(response.data[0]['severity'], Notification.Severity.CRITICAL)
        notification_id = response.data[0]['id']
        self.assertEqual(self.client.get('/api/notifications/').data[0]['id'], notification_id)

        read = self.client.post(f'/api/notifications/{notification_id}/read/', {}, format='json')
        self.assertTrue(read.data['is_read'])

        dismissed = self.client.post(f'/api/notifications/{notification_id}/dismiss/', {}, format='json')
        self.assertEqual(dismissed.status_code, 204)
        self.assertEqual(self.client.get('/api/notifications/').data, [])

    def test_stock_alert_resolves_after_restock_and_read_all_marks_active_alerts(self):
        self.client.get('/api/notifications/')
        self.product.quantity = 3
        self.product.save(update_fields=['quantity'])

        response = self.client.get('/api/notifications/')
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['severity'], Notification.Severity.WARNING)

        result = self.client.post('/api/notifications/read_all/', {}, format='json')
        self.assertEqual(result.data['updated'], 1)
        self.assertTrue(self.client.get('/api/notifications/').data[0]['is_read'])

        self.product.quantity = 6
        self.product.save(update_fields=['quantity'])
        self.assertEqual(self.client.get('/api/notifications/').data, [])

        self.product.quantity = 0
        self.product.save(update_fields=['quantity'])
        returned = self.client.get('/api/notifications/').data
        self.assertEqual(len(returned), 1)
        self.assertFalse(returned[0]['is_read'])


class StaffPayrollTests(APITestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username='payroll-admin', password='test-password')
        self.client.force_authenticate(user=self.admin)

    def create_worker(self, **overrides):
        payload = {
            'full_name': 'Amina Nansubuga',
            'email': 'amina@example.test',
            'job_title': 'Warehouse Associate',
            'department': 'Warehouse & Logistics',
            'pay_basis': 'monthly',
            'pay_rate': '1000000.00',
            'hours_per_period': '160.00',
            'withholding_percent': '10.00',
            'benefit_deduction': '20000.00',
            'status': 'active',
            'hire_date': '2025-02-01',
        }
        payload.update(overrides)
        return self.client.post('/api/staff/workers/', payload, format='json')

    def test_staff_and_payroll_api_requires_superuser(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get('/api/staff/dashboard/').status_code, 403)
        self.assertEqual(self.client.post('/api/staff/workers/', {}, format='json').status_code, 403)
        self.assertEqual(self.client.post('/api/staff/attendance/record_day/', {}, format='json').status_code, 403)
        self.assertEqual(self.client.post('/api/staff/payroll-runs/generate/', {'period': '2025-02'}, format='json').status_code, 403)

    def test_worker_validation_and_salary_update_recalculates_unpaid_payroll(self):
        invalid = self.create_worker(withholding_percent='80.00', benefit_deduction='250000.00')
        self.assertEqual(invalid.status_code, 400)
        self.assertFalse(StaffMember.objects.exists())

        created = self.create_worker()
        self.assertEqual(created.status_code, 201)
        self.assertTrue(created.data['employee_number'].startswith('EMP-'))
        worker_id = created.data['id']

        dashboard = self.client.get('/api/staff/dashboard/').data
        self.assertEqual(dashboard['summary']['active_workers'], 1)
        self.assertEqual(dashboard['summary']['gross_total'], Decimal('1000000.00'))
        self.assertEqual(dashboard['summary']['net_total'], Decimal('880000.00'))

        generated = self.client.post('/api/staff/payroll-runs/generate/', {'period': '2025-02'}, format='json')
        self.assertEqual(generated.status_code, 201)
        self.assertEqual(generated.data['gross_total'], '1000000.00')
        self.assertEqual(generated.data['withholding_total'], '100000.00')
        self.assertEqual(generated.data['benefits_total'], '20000.00')
        self.assertEqual(generated.data['net_total'], '880000.00')
        self.assertEqual(len(generated.data['lines']), 1)

        updated = self.client.patch(
            f'/api/staff/workers/{worker_id}/',
            {'pay_rate': '1500000.00'},
            format='json',
        )
        self.assertEqual(updated.status_code, 200)
        line = PayrollLine.objects.get(run_id=generated.data['id'])
        self.assertEqual(line.gross_pay, Decimal('1500000.00'))
        self.assertEqual(line.withholding, Decimal('150000.00'))
        self.assertEqual(line.net_pay, Decimal('1330000.00'))
        run = PayrollRun.objects.get(pk=generated.data['id'])
        self.assertEqual(run.gross_total, Decimal('1500000.00'))
        self.assertEqual(run.net_total, Decimal('1330000.00'))
        dashboard = self.client.get('/api/staff/dashboard/?period=2025-02').data
        self.assertEqual(dashboard['summary']['gross_total'], Decimal('1500000.00'))
        self.assertEqual(dashboard['summary']['net_total'], Decimal('1330000.00'))

        duplicate = self.client.post('/api/staff/payroll-runs/generate/', {'period': '2025-02'}, format='json')
        self.assertEqual(duplicate.status_code, 400)
        paid = self.client.post(f"/api/staff/payroll-runs/{generated.data['id']}/mark_paid/", {}, format='json')
        self.assertEqual(paid.status_code, 200)
        self.assertEqual(paid.data['status'], PayrollRun.Status.PAID)
        self.assertIsNotNone(paid.data['paid_at'])
        self.assertTrue(SecurityAuditEvent.objects.filter(action='payroll.marked_paid', target_id='2025-02').exists())

    def test_salary_update_does_not_change_paid_payroll(self):
        created = self.create_worker()
        generated = self.client.post('/api/staff/payroll-runs/generate/', {'period': '2025-02'}, format='json')
        self.assertEqual(generated.status_code, 201)
        paid = self.client.post(
            f"/api/staff/payroll-runs/{generated.data['id']}/mark_paid/",
            {},
            format='json',
        )
        self.assertEqual(paid.status_code, 200)

        updated = self.client.patch(
            f"/api/staff/workers/{created.data['id']}/",
            {'pay_rate': '1500000.00'},
            format='json',
        )
        self.assertEqual(updated.status_code, 200)
        line = PayrollLine.objects.get(run_id=generated.data['id'])
        self.assertEqual(line.gross_pay, Decimal('1000000.00'))
        self.assertEqual(line.net_pay, Decimal('880000.00'))

    def test_hourly_worker_pay_and_invalid_period(self):
        created = self.create_worker(
            full_name='Daniel Okello',
            email='daniel@example.test',
            pay_basis='hourly',
            pay_rate='12500.00',
            hours_per_period='120.00',
            withholding_percent='0.00',
            benefit_deduction='0.00',
        )
        self.assertEqual(created.status_code, 201)
        invalid_period = self.client.post('/api/staff/payroll-runs/generate/', {'period': 'Feb 2025'}, format='json')
        self.assertEqual(invalid_period.status_code, 400)

        generated = self.client.post('/api/staff/payroll-runs/generate/', {'period': '2025-02'}, format='json')
        self.assertEqual(generated.status_code, 201)
        self.assertEqual(generated.data['gross_total'], '1500000.00')
        self.assertEqual(generated.data['lines'][0]['hours'], '120.00')

    def test_task_pay_rates_are_added_to_monthly_payroll_and_snapshotted(self):
        worker = self.create_worker()
        worker_id = worker.data['id']
        daily = self.client.post('/api/staff/tasks/', {
            'name': 'Package orders',
            'pay_basis': 'daily',
            'pay_rate': '100.00',
        }, format='json')
        hourly = self.client.post('/api/staff/tasks/', {
            'name': 'Load trucks',
            'pay_basis': 'hourly',
            'pay_rate': '50.00',
        }, format='json')
        monthly = self.client.post('/api/staff/tasks/', {
            'name': 'Stock management',
            'pay_basis': 'monthly',
            'pay_rate': '500.00',
        }, format='json')
        self.assertEqual((daily.status_code, hourly.status_code, monthly.status_code), (201, 201, 201))

        for work_date in ('2025-02-03', '2025-02-04'):
            attendance = self.client.post('/api/staff/attendance/record_day/', {
                'date': work_date,
                'records': [{'worker': worker_id, 'attended': True}],
            }, format='json')
            self.assertEqual(attendance.status_code, 200)

        first_day = self.client.post('/api/staff/task-entries/record_day/', {
            'date': '2025-02-03',
            'records': [
                {'worker': worker_id, 'task': daily.data['id']},
                {'worker': worker_id, 'task': hourly.data['id'], 'hours': '2.00'},
                {'worker': worker_id, 'task': monthly.data['id']},
            ],
        }, format='json')
        self.assertEqual(first_day.status_code, 200)
        self.assertEqual(len(first_day.data), 3)
        basis_change = self.client.patch(
            f"/api/staff/tasks/{daily.data['id']}/",
            {'pay_basis': 'monthly'},
            format='json',
        )
        self.assertEqual(basis_change.status_code, 400)

        updated_hourly = self.client.patch(
            f"/api/staff/tasks/{hourly.data['id']}/",
            {'pay_rate': '75.00'},
            format='json',
        )
        self.assertEqual(updated_hourly.status_code, 200)
        updated_monthly = self.client.patch(
            f"/api/staff/tasks/{monthly.data['id']}/",
            {'pay_rate': '750.00'},
            format='json',
        )
        self.assertEqual(updated_monthly.status_code, 200)
        second_day = self.client.post('/api/staff/task-entries/record_day/', {
            'date': '2025-02-04',
            'records': [
                {'worker': worker_id, 'task': daily.data['id']},
                {'worker': worker_id, 'task': monthly.data['id']},
            ],
        }, format='json')
        self.assertEqual(second_day.status_code, 200)

        dashboard = self.client.get('/api/staff/dashboard/?period=2025-02').data
        self.assertEqual(dashboard['workers'][0]['period_task_pay'], Decimal('1100.00'))
        self.assertEqual(dashboard['summary']['task_pay_total'], Decimal('1100.00'))
        self.assertEqual(dashboard['summary']['gross_total'], Decimal('1001100.00'))

        generated = self.client.post('/api/staff/payroll-runs/generate/', {'period': '2025-02'}, format='json')
        self.assertEqual(generated.status_code, 201)
        self.assertEqual(generated.data['gross_total'], '1001100.00')
        self.assertEqual(generated.data['lines'][0]['task_pay'], '1100.00')
        self.assertEqual(generated.data['lines'][0]['withholding'], '100110.00')
        self.assertEqual(generated.data['lines'][0]['net_pay'], '880990.00')
        hourly_assignment = StaffTaskEntry.objects.get(
            worker_id=worker_id,
            task_id=hourly.data['id'],
            date='2025-02-03',
        )
        first_monthly_assignment = StaffTaskEntry.objects.get(
            worker_id=worker_id,
            task_id=monthly.data['id'],
            date='2025-02-03',
        )
        second_monthly_assignment = StaffTaskEntry.objects.get(
            worker_id=worker_id,
            task_id=monthly.data['id'],
            date='2025-02-04',
        )
        self.assertEqual(hourly_assignment.pay_rate, Decimal('75.00'))
        self.assertEqual(first_monthly_assignment.pay_rate, Decimal('750.00'))
        self.assertEqual(second_monthly_assignment.pay_rate, Decimal('750.00'))

        changed_after_generation = self.client.patch(
            f"/api/staff/tasks/{hourly.data['id']}/",
            {'pay_rate': '100.00'},
            format='json',
        )
        self.assertEqual(changed_after_generation.status_code, 200)
        hourly_assignment.refresh_from_db()
        self.assertEqual(hourly_assignment.pay_rate, Decimal('75.00'))
        unchanged_payroll = self.client.get('/api/staff/payroll-runs/').data[0]
        self.assertEqual(unchanged_payroll['lines'][0]['task_pay'], '1100.00')

        locked = self.client.post('/api/staff/task-entries/record_day/', {
            'date': '2025-02-03',
            'records': [],
        }, format='json')
        self.assertEqual(locked.status_code, 400)

    def test_hourly_task_requires_hours_and_assignment_cannot_duplicate(self):
        worker = self.create_worker()
        task = self.client.post('/api/staff/tasks/', {
            'name': 'Forklift operation',
            'pay_basis': 'hourly',
            'pay_rate': '100.00',
        }, format='json')
        self.client.post('/api/staff/attendance/record_day/', {
            'date': '2025-02-03',
            'records': [{'worker': worker.data['id'], 'attended': True}],
        }, format='json')
        missing_hours = self.client.post('/api/staff/task-entries/record_day/', {
            'date': '2025-02-03',
            'records': [{'worker': worker.data['id'], 'task': task.data['id']}],
        }, format='json')
        self.assertEqual(missing_hours.status_code, 400)
        duplicate = self.client.post('/api/staff/task-entries/record_day/', {
            'date': '2025-02-03',
            'records': [
                {'worker': worker.data['id'], 'task': task.data['id'], 'hours': '1.00'},
                {'worker': worker.data['id'], 'task': task.data['id'], 'hours': '2.00'},
            ],
        }, format='json')
        self.assertEqual(duplicate.status_code, 400)
        self.assertFalse(StaffTaskEntry.objects.exists())

    def test_target_task_pay_uses_highest_reached_tier_and_recalculates_before_payroll(self):
        worker = self.create_worker()
        missing_target = self.client.post('/api/staff/tasks/', {
            'name': 'Pack cartons without target',
            'pay_basis': 'target',
            'pay_rate': '750.00',
        }, format='json')
        self.assertEqual(missing_target.status_code, 400)

        task = self.client.post('/api/staff/tasks/', {
            'name': 'Pack target cartons',
            'pay_basis': 'target',
            'pay_rate': '1500.00',
            'target_tiers': [
                {'target_quantity': 15, 'amount': '1500.00'},
                {'target_quantity': 10, 'amount': '750.00'},
                {'target_quantity': 12, 'amount': '1000.00'},
            ],
        }, format='json')
        self.assertEqual(task.status_code, 201)
        self.assertEqual(task.data['target_tiers'], [
            {'target_quantity': 10, 'amount': '750.00'},
            {'target_quantity': 12, 'amount': '1000.00'},
            {'target_quantity': 15, 'amount': '1500.00'},
        ])
        task_id = task.data['id']

        for work_date in ('2025-02-03', '2025-02-04', '2025-02-05', '2025-02-06'):
            attendance = self.client.post('/api/staff/attendance/record_day/', {
                'date': work_date,
                'records': [{'worker': worker.data['id'], 'attended': True}],
            }, format='json')
            self.assertEqual(attendance.status_code, 200)

        missing_units = self.client.post('/api/staff/task-entries/record_day/', {
            'date': '2025-02-03',
            'records': [{'worker': worker.data['id'], 'task': task_id}],
        }, format='json')
        self.assertEqual(missing_units.status_code, 400)

        for work_date, units in (
            ('2025-02-03', 9),
            ('2025-02-04', 10),
            ('2025-02-05', 12),
            ('2025-02-06', 15),
        ):
            recorded = self.client.post('/api/staff/task-entries/record_day/', {
                'date': work_date,
                'records': [{
                    'worker': worker.data['id'],
                    'task': task_id,
                    'units_worked': units,
                }],
            }, format='json')
            self.assertEqual(recorded.status_code, 200, recorded.data)
            self.assertEqual(recorded.data[0]['target_tiers'], task.data['target_tiers'])
            self.assertEqual(recorded.data[0]['units_worked'], units)

        updated_tiers = [
            {'target_quantity': 10, 'amount': '800.00'},
            {'target_quantity': 12, 'amount': '1100.00'},
            {'target_quantity': 15, 'amount': '1600.00'},
        ]
        updated_task = self.client.patch(
            f'/api/staff/tasks/{task_id}/',
            {'target_tiers': updated_tiers},
            format='json',
        )
        self.assertEqual(updated_task.status_code, 200, updated_task.data)
        updated_entries = self.client.get('/api/staff/task-entries/?period=2025-02')
        self.assertEqual(updated_entries.status_code, 200)
        self.assertTrue(all(entry['target_tiers'] == updated_task.data['target_tiers'] for entry in updated_entries.data))

        dashboard = self.client.get('/api/staff/dashboard/?period=2025-02').data
        self.assertEqual(dashboard['workers'][0]['period_task_pay'], Decimal('3500.00'))
        self.assertEqual(dashboard['summary']['task_pay_total'], Decimal('3500.00'))
        self.assertEqual(dashboard['summary']['gross_total'], Decimal('1003500.00'))

        payroll = self.client.post('/api/staff/payroll-runs/generate/', {'period': '2025-02'}, format='json')
        self.assertEqual(payroll.status_code, 201)
        self.assertEqual(payroll.data['lines'][0]['task_pay'], '3500.00')
        self.assertEqual(payroll.data['lines'][0]['gross_pay'], '1003500.00')

        updated_after_payroll = [
            {'target_quantity': 10, 'amount': '900.00'},
            {'target_quantity': 12, 'amount': '1200.00'},
            {'target_quantity': 15, 'amount': '1800.00'},
        ]
        changed_after_generation = self.client.patch(
            f'/api/staff/tasks/{task_id}/',
            {'target_tiers': updated_after_payroll},
            format='json',
        )
        self.assertEqual(changed_after_generation.status_code, 200)
        unchanged_payroll = self.client.get('/api/staff/payroll-runs/').data[0]
        self.assertEqual(unchanged_payroll['lines'][0]['task_pay'], '3500.00')

    def test_permanent_task_assignments_create_pay_entries_only_for_attended_days(self):
        worker = self.create_worker()
        task = self.client.post('/api/staff/tasks/', {
            'name': 'Daily packing',
            'pay_basis': 'daily',
            'pay_rate': '250.00',
        }, format='json')
        assignment = self.client.post('/api/staff/task-assignments/', {
            'worker': worker.data['id'],
            'task': task.data['id'],
            'assigned_from': '2025-02-01',
        }, format='json')
        self.assertEqual(assignment.status_code, 201)

        absent_day = self.client.post('/api/staff/attendance/record_day/', {
            'date': '2025-02-03',
            'records': [{'worker': worker.data['id'], 'attended': False}],
        }, format='json')
        self.assertEqual(absent_day.status_code, 200)
        self.assertFalse(StaffTaskEntry.objects.filter(date='2025-02-03').exists())

        attended_day = self.client.post('/api/staff/attendance/record_day/', {
            'date': '2025-02-04',
            'records': [{'worker': worker.data['id'], 'attended': True}],
        }, format='json')
        self.assertEqual(attended_day.status_code, 200)
        entry = StaffTaskEntry.objects.get(date='2025-02-04')
        self.assertEqual(entry.assignment_type, StaffTaskEntry.AssignmentType.PERMANENT)
        self.assertEqual(entry.pay_rate, Decimal('250.00'))

        unassigned = self.client.patch(
            f"/api/staff/task-assignments/{assignment.data['id']}/",
            {'is_active': False},
            format='json',
        )
        self.assertEqual(unassigned.status_code, 200)
        next_day = self.client.post('/api/staff/attendance/record_day/', {
            'date': '2025-02-05',
            'records': [{'worker': worker.data['id'], 'attended': True}],
        }, format='json')
        self.assertEqual(next_day.status_code, 200)
        self.assertFalse(StaffTaskEntry.objects.filter(date='2025-02-05').exists())
        self.assertTrue(StaffTaskEntry.objects.filter(id=entry.id).exists())

    def test_removing_permanent_task_deletes_selected_day_and_unassigns_future_days(self):
        worker = self.create_worker()
        task = self.client.post('/api/staff/tasks/', {
            'name': 'Permanent packing',
            'pay_basis': 'daily',
            'pay_rate': '250.00',
        }, format='json')
        assignment = self.client.post('/api/staff/task-assignments/', {
            'worker': worker.data['id'],
            'task': task.data['id'],
            'assigned_from': '2025-02-01',
        }, format='json')
        self.assertEqual(assignment.status_code, 201)

        for work_date in ('2025-02-04', '2025-02-05'):
            attendance = self.client.post('/api/staff/attendance/record_day/', {
                'date': work_date,
                'records': [{'worker': worker.data['id'], 'attended': True}],
            }, format='json')
            self.assertEqual(attendance.status_code, 200)

        removed = self.client.post('/api/staff/task-entries/remove_permanent/', {
            'date': '2025-02-04',
            'worker': worker.data['id'],
            'task': task.data['id'],
        }, format='json')
        self.assertEqual(removed.status_code, 200, removed.data)
        self.assertTrue(removed.data['removed'])
        self.assertTrue(removed.data['permanent_assignment_deactivated'])
        self.assertFalse(StaffTaskEntry.objects.filter(
            worker_id=worker.data['id'],
            task_id=task.data['id'],
            date='2025-02-04',
        ).exists())
        self.assertTrue(StaffTaskEntry.objects.filter(
            worker_id=worker.data['id'],
            task_id=task.data['id'],
            date='2025-02-05',
        ).exists())
        self.assertFalse(self.client.get('/api/staff/task-assignments/?active=true').data)

        next_day = self.client.post('/api/staff/attendance/record_day/', {
            'date': '2025-02-06',
            'records': [{'worker': worker.data['id'], 'attended': True}],
        }, format='json')
        self.assertEqual(next_day.status_code, 200)
        self.assertFalse(StaffTaskEntry.objects.filter(
            worker_id=worker.data['id'],
            task_id=task.data['id'],
            date='2025-02-06',
        ).exists())

        payroll = self.client.post('/api/staff/payroll-runs/generate/', {'period': '2025-02'}, format='json')
        self.assertEqual(payroll.status_code, 201)
        locked_removal = self.client.post('/api/staff/task-entries/remove_permanent/', {
            'date': '2025-02-05',
            'worker': worker.data['id'],
            'task': task.data['id'],
        }, format='json')
        self.assertEqual(locked_removal.status_code, 400)
        self.assertTrue(StaffTaskEntry.objects.filter(
            worker_id=worker.data['id'],
            task_id=task.data['id'],
            date='2025-02-05',
        ).exists())

    def test_same_permanent_task_can_be_assigned_to_multiple_workers(self):
        first_worker = self.create_worker(full_name='Amina Nansubuga')
        second_worker = self.create_worker(
            full_name='Daniel Okello',
            email='daniel@example.test',
        )
        task = self.client.post('/api/staff/tasks/', {
            'name': 'Shared packing task',
            'pay_basis': 'daily',
            'pay_rate': '250.00',
        }, format='json')
        self.assertEqual(task.status_code, 201)

        assignments = [
            self.client.post('/api/staff/task-assignments/', {
                'worker': worker.data['id'],
                'task': task.data['id'],
                'assigned_from': '2025-02-01',
            }, format='json')
            for worker in (first_worker, second_worker)
        ]
        self.assertEqual([assignment.status_code for assignment in assignments], [201, 201])

        attendance = self.client.post('/api/staff/attendance/record_day/', {
            'date': '2025-02-04',
            'records': [
                {'worker': first_worker.data['id'], 'attended': True},
                {'worker': second_worker.data['id'], 'attended': True},
            ],
        }, format='json')
        self.assertEqual(attendance.status_code, 200)
        entries = StaffTaskEntry.objects.filter(date='2025-02-04', task_id=task.data['id'])
        self.assertEqual(entries.count(), 2)
        self.assertEqual(set(entries.values_list('worker_id', flat=True)), {
            first_worker.data['id'],
            second_worker.data['id'],
        })

    def test_bulk_attendance_save_handles_many_permanent_assignments_efficiently(self):
        workers = [
            self.create_worker(
                full_name=f'Worker {index}',
                email=f'worker{index}@example.test',
            ).data
            for index in range(10)
        ]
        task = self.client.post('/api/staff/tasks/', {
            'name': 'Bulk attendance task',
            'pay_basis': 'daily',
            'pay_rate': '250.00',
        }, format='json')
        self.assertEqual(task.status_code, 201)
        for worker in workers:
            assignment = self.client.post('/api/staff/task-assignments/', {
                'worker': worker['id'],
                'task': task.data['id'],
                'assigned_from': '2025-02-01',
            }, format='json')
            self.assertEqual(assignment.status_code, 201)

        payload = {
            'date': '2025-02-04',
            'records': [{'worker': worker['id'], 'attended': True} for worker in workers],
        }
        with CaptureQueriesContext(connection) as queries:
            attendance = self.client.post(
                '/api/staff/attendance/record_day/',
                payload,
                format='json',
            )
        self.assertEqual(attendance.status_code, 200, attendance.data)
        self.assertLess(len(queries), 45)
        self.assertEqual(len(attendance.data), len(workers))

        repeated = self.client.post('/api/staff/attendance/record_day/', payload, format='json')
        self.assertEqual(repeated.status_code, 200, repeated.data)
        self.assertEqual(
            StaffAttendance.objects.filter(date='2025-02-04').count(),
            len(workers),
        )
        self.assertEqual(
            StaffTaskEntry.objects.filter(date='2025-02-04', task_id=task.data['id']).count(),
            len(workers),
        )

    def test_permanent_assignment_credits_attended_day_from_selected_start_date(self):
        worker = self.create_worker()
        task = self.client.post('/api/staff/tasks/', {
            'name': 'Selected-date packing',
            'pay_basis': 'daily',
            'pay_rate': '300.00',
        }, format='json')
        self.assertEqual(task.status_code, 201)
        attendance = self.client.post('/api/staff/attendance/record_day/', {
            'date': '2025-02-04',
            'records': [{'worker': worker.data['id'], 'attended': True}],
        }, format='json')
        self.assertEqual(attendance.status_code, 200)

        assignment = self.client.post('/api/staff/task-assignments/', {
            'worker': worker.data['id'],
            'task': task.data['id'],
            'assigned_from': '2025-02-04',
        }, format='json')
        self.assertEqual(assignment.status_code, 201)
        entry = StaffTaskEntry.objects.get(worker_id=worker.data['id'], task_id=task.data['id'])
        self.assertEqual(entry.date.isoformat(), '2025-02-04')
        self.assertEqual(entry.pay_rate, Decimal('300.00'))

    def test_daily_task_pay_replaces_target_wage_on_assigned_day(self):
        worker = self.create_worker(
            pay_basis='daily',
            pay_rate='25000.00',
            withholding_percent='0.00',
            benefit_deduction='0.00',
        )
        task = self.client.post('/api/staff/tasks/', {
            'name': 'Order packing',
            'pay_basis': 'daily',
            'pay_rate': '250.00',
        }, format='json')
        self.assertEqual(task.status_code, 201)

        attended = self.client.post('/api/staff/attendance/record_day/', {
            'date': '2025-02-03',
            'records': [{'worker': worker.data['id'], 'attended': True, 'output_quantity': 15}],
        }, format='json')
        self.assertEqual(attended.status_code, 200)
        task_work = self.client.post('/api/staff/task-entries/record_day/', {
            'date': '2025-02-03',
            'records': [{'worker': worker.data['id'], 'task': task.data['id']}],
        }, format='json')
        self.assertEqual(task_work.status_code, 200)

        non_task_day = self.client.post('/api/staff/attendance/record_day/', {
            'date': '2025-02-04',
            'records': [{'worker': worker.data['id'], 'attended': True, 'output_quantity': 14}],
        }, format='json')
        self.assertEqual(non_task_day.status_code, 200)
        attendance_records = self.client.get('/api/staff/attendance/?period=2025-02')
        self.assertEqual(attendance_records.status_code, 200)
        attendance_by_date = {record['date']: record for record in attendance_records.data}
        self.assertEqual(
            self.client.get('/api/staff/attendance/?period=2025-02').data,
            attendance_records.data,
        )
        self.assertEqual(attendance_by_date['2025-02-03']['daily_wage'], '0.00')
        self.assertEqual(attendance_by_date['2025-02-04']['daily_wage'], '6000.00')
        task_entries = self.client.get('/api/staff/task-entries/?period=2025-02')
        self.assertEqual(task_entries.status_code, 200)
        self.assertEqual(len(task_entries.data), 1)
        self.assertEqual(task_entries.data[0]['worker'], worker.data['id'])
        self.assertEqual(task_entries.data[0]['task'], task.data['id'])
        self.assertEqual(
            self.client.get('/api/staff/task-entries/?period=2025-02').data,
            task_entries.data,
        )

        payroll = self.client.post('/api/staff/payroll-runs/generate/', {'period': '2025-02'}, format='json')
        self.assertEqual(payroll.status_code, 201)
        self.assertEqual(payroll.data['lines'][0]['task_pay'], '250.00')
        self.assertEqual(payroll.data['lines'][0]['gross_pay'], '6250.00')

    def test_daily_attendance_applies_unit_based_weekday_and_sunday_pay_rates(self):
        created = self.create_worker(
            full_name='Daniel Okello',
            email='daniel@example.test',
            pay_basis='daily',
            pay_rate='25000.00',
            withholding_percent='10.00',
            benefit_deduction='5000.00',
        )
        worker_id = created.data['id']
        expected_wages = {
            '2025-02-03': (15, '7000.00'),
            '2025-02-04': (12, '6000.00'),
            '2025-02-05': (9, '4000.00'),
            '2025-02-06': (10, '5000.00'),
            '2025-02-07': (11, '5000.00'),
            '2025-02-08': (12, '6000.00'),
            '2025-02-10': (8, '4000.00'),
            '2025-02-11': (9, '4000.00'),
            '2025-02-09': (15, '7000.00'),
            '2025-02-16': (12, '6000.00'),
            '2025-02-23': (10, '5000.00'),
            '2025-02-02': (7, '0.00'),
        }
        for work_date, (units, _) in expected_wages.items():
            response = self.client.post('/api/staff/attendance/record_day/', {
                'date': work_date,
                'records': [{'worker': worker_id, 'attended': True, 'output_quantity': units}],
            }, format='json')
            self.assertEqual(response.status_code, 200)

        daily_records = {record['date']: record for record in self.client.get('/api/staff/attendance/?period=2025-02').data}
        for work_date, (units, wage) in expected_wages.items():
            self.assertEqual(daily_records[work_date]['daily_wage'], wage)
            self.assertEqual(daily_records[work_date]['output_quantity'], units)

        month_records = self.client.get('/api/staff/attendance/?period=2025-02')
        self.assertEqual(month_records.status_code, 200)
        self.assertEqual(len(month_records.data), 12)
        self.assertEqual({record['date'] for record in month_records.data}, set(expected_wages))

        dashboard = self.client.get('/api/staff/dashboard/?period=2025-02').data
        self.assertEqual(dashboard['workers'][0]['period_days_worked'], 12)
        self.assertEqual(dashboard['workers'][0]['period_gross'], Decimal('59000.00'))
        self.assertEqual(dashboard['summary']['gross_total'], Decimal('59000.00'))

        generated = self.client.post('/api/staff/payroll-runs/generate/', {'period': '2025-02'}, format='json')
        self.assertEqual(generated.status_code, 201)
        self.assertEqual(generated.data['gross_total'], '59000.00')
        self.assertEqual(generated.data['lines'][0]['days_worked'], 12)
        self.assertEqual(generated.data['lines'][0]['withholding'], '5900.00')
        self.assertEqual(generated.data['lines'][0]['benefits'], '5000.00')
        self.assertEqual(generated.data['lines'][0]['net_pay'], '48100.00')
        locked = self.client.post('/api/staff/attendance/record_day/', {
            'date': '2025-02-03',
            'records': [{'worker': worker_id, 'attended': True, 'output_quantity': 100}],
        }, format='json')
        self.assertEqual(locked.status_code, 400)
        self.assertEqual(StaffAttendance.objects.get(worker_id=worker_id, date='2025-02-03').daily_wage, Decimal('7000.00'))

    def test_sunday_attendance_pays_requested_unit_thresholds(self):
        worker = self.create_worker(
            full_name='Sunday Threshold Worker',
            email='sunday-threshold@example.test',
            pay_basis='daily',
        )
        expected_wages = {
            '2025-03-02': (8, '4000.00'),
            '2025-03-09': (10, '5000.00'),
            '2025-03-16': (12, '6000.00'),
            '2025-03-23': (15, '7000.00'),
        }

        for work_date, (units, expected_wage) in expected_wages.items():
            response = self.client.post('/api/staff/attendance/record_day/', {
                'date': work_date,
                'records': [{
                    'worker': worker.data['id'],
                    'attended': True,
                    'output_quantity': units,
                }],
            }, format='json')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data[0]['daily_wage'], expected_wage)

    def test_supervisor_can_override_daily_wage_below_eight_units(self):
        worker = self.create_worker(pay_basis='daily', benefit_deduction='0.00')
        worker_id = worker.data['id']
        saved = self.client.post('/api/staff/attendance/record_day/', {
            'date': '2025-02-03',
            'records': [{
                'worker': worker_id,
                'attended': True,
                'output_quantity': 7,
                'daily_wage_override': '8250.50',
            }],
        }, format='json')

        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.data[0]['daily_wage_override'], '8250.50')
        self.assertEqual(saved.data[0]['daily_wage'], '8250.50')
        self.assertEqual(StaffAttendance.objects.get(worker_id=worker_id).daily_wage, Decimal('8250.50'))

        invalid = self.client.post('/api/staff/attendance/record_day/', {
            'date': '2025-02-04',
            'records': [{
                'worker': worker_id,
                'attended': True,
                'output_quantity': 8,
                'daily_wage_override': '8250.50',
            }],
        }, format='json')
        self.assertEqual(invalid.status_code, 400)

        sunday_worker = self.create_worker(
            full_name='Sunday Override Worker',
            email='sunday-override@example.test',
            pay_basis='daily',
            benefit_deduction='0.00',
        )
        sunday_saved = self.client.post('/api/staff/attendance/record_day/', {
            'date': '2025-02-09',
            'records': [{
                'worker': sunday_worker.data['id'],
                'attended': True,
                'output_quantity': 7,
                'daily_wage_override': '4250.25',
            }],
        }, format='json')
        self.assertEqual(sunday_saved.status_code, 200)
        self.assertEqual(sunday_saved.data[0]['daily_wage'], '4250.25')

        generated = self.client.post('/api/staff/payroll-runs/generate/', {'period': '2025-02'}, format='json')
        self.assertEqual(generated.status_code, 201)
        self.assertEqual(generated.data['gross_total'], '12500.75')

    def test_attendance_can_be_recorded_for_monthly_worker_without_daily_wage(self):
        created = self.create_worker()
        response = self.client.post('/api/staff/attendance/record_day/', {
            'date': '2025-02-03',
            'records': [{'worker': created.data['id'], 'attended': True, 'output_quantity': 0}],
        }, format='json')

        self.assertEqual(response.status_code, 200)
        record = StaffAttendance.objects.get(worker_id=created.data['id'], date='2025-02-03')
        self.assertTrue(record.attended)
        self.assertEqual(record.daily_wage, Decimal('0.00'))

    def test_attendance_response_reuses_validated_workers(self):
        workers = [
            self.create_worker(full_name=f'Attendance Worker {index}').data
            for index in range(2)
        ]
        with CaptureQueriesContext(connection) as queries:
            response = self.client.post('/api/staff/attendance/record_day/', {
                'date': '2025-02-03',
                'records': [
                    {'worker': worker['id'], 'attended': True, 'output_quantity': 0}
                    for worker in workers
                ],
            }, format='json')

        self.assertEqual(response.status_code, 200)
        worker_lookups = [
            query for query in queries.captured_queries
            if 'from "inventory_staffmember" where "inventory_staffmember"."id" =' in query['sql'].lower()
        ]
        self.assertEqual(
            len(worker_lookups),
            len(workers),
        )
        self.assertEqual(
            [record['worker_name'] for record in response.data],
            [worker['full_name'] for worker in workers],
        )


class SystemSettingsTests(APITestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username='settings-admin', password='test-password')
        self.client.force_authenticate(user=self.admin)

    def test_settings_return_defaults_and_persist_updates_with_audit(self):
        initial = self.client.get('/api/settings/')
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.data['settings']['organization']['currency'], 'UGX')

        updated = self.client.patch('/api/settings/', {
            'settings': {'organization': {'business_name': 'StockPulse Ltd.', 'currency': 'USD'}, 'operations': {'reorder_threshold': 20}},
        }, format='json')

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data['settings']['organization']['business_name'], 'StockPulse Ltd.')
        self.assertEqual(updated.data['settings']['organization']['currency'], 'USD')
        self.assertEqual(updated.data['settings']['operations']['reorder_threshold'], 20)
        self.assertEqual(SystemSetting.objects.count(), 3)
        self.assertEqual(SecurityAuditEvent.objects.filter(action='settings.updated').count(), 3)

    def test_anonymous_users_cannot_read_or_update_settings(self):
        self.client.force_authenticate(user=None)
        read = self.client.get('/api/settings/')
        update = self.client.patch('/api/settings/', {'settings': {'organization': {'business_name': 'Unauthorized'}}}, format='json')

        self.assertEqual(read.status_code, 403)
        self.assertEqual(update.status_code, 403)
        self.assertFalse(SystemSetting.objects.exists())

    def test_settings_reject_unknown_keys_and_wrong_types(self):
        unknown = self.client.patch('/api/settings/', {'settings': {'organization': {'unknown': 'value'}}}, format='json')
        wrong_type = self.client.patch('/api/settings/', {'settings': {'operations': {'reorder_threshold': 'many'}}}, format='json')
        invalid_currency = self.client.patch('/api/settings/', {'settings': {'organization': {'currency': 'US'}}}, format='json')

        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(wrong_type.status_code, 400)
        self.assertEqual(invalid_currency.status_code, 400)
        self.assertFalse(SystemSetting.objects.exists())

    @patch('inventory.settings_views.urlopen')
    def test_exchange_rates_are_available_without_authentication(self, mock_urlopen):
        cache.clear()
        payload = {
            'result': 'success',
            'base_code': 'UGX',
            'time_last_update_utc': 'Sun, 04 Oct 2026 00:00:01 +0000',
            'rates': {'UGX': 1, 'USD': 0.00027, 'EUR': 0.00025},
        }
        SystemSetting.objects.create(category='organization', key='currency', value='USD')
        mock_urlopen.return_value = BytesIO(json.dumps(payload).encode())
        self.client.force_authenticate(user=None)

        response = self.client.get('/api/exchange-rates/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['base_currency'], 'UGX')
        self.assertEqual(response.data['currency'], 'USD')
        self.assertEqual(response.data['rates']['USD'], 0.00027)
        self.assertEqual(response.data['updated_at'], payload['time_last_update_utc'])

    def test_exchange_rate_service_failure_is_reported(self):
        cache.clear()
        self.client.force_authenticate(user=None)

        with patch('inventory.settings_views.urlopen', side_effect=URLError('network unavailable')):
            response = self.client.get('/api/exchange-rates/')

        self.assertEqual(response.status_code, 503)
        self.assertIn('temporarily unavailable', response.data['detail'])


class InventoryAdjustmentTests(AdminAPITestCase):
    def setUp(self):
        super().setUp()
        category = Category.objects.create(name='Test inventory')
        self.product = Product.objects.create(
            sku='INV-001',
            name='Test product',
            category=category,
            quantity=10,
            reorder_level=2,
            unit_price='12.00',
            cost_price='8.00',
        )

    def test_damage_adjustment_decreases_stock_and_records_audit_details(self):
        response = self.client.post('/api/inventory/adjustments/', {
            'product': self.product.id,
            'adjustment_type': 'damage',
            'quantity': 2,
            'reason': 'Damaged during handling',
            'reference': 'QA-001',
            'notes': 'Broken packaging',
        }, format='json')

        self.assertEqual(response.status_code, 201)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 8)
        movement = StockMovement.objects.get()
        self.assertEqual(movement.quantity, -2)
        self.assertEqual(movement.note, 'Damaged during handling: Broken packaging')
        self.assertEqual(movement.reference, 'QA-001')

    def test_stock_movement_history_filters_to_selected_lookback(self):
        recent = StockMovement.objects.create(product=self.product, movement_type='adjustment', quantity=1)
        older = StockMovement.objects.create(product=self.product, movement_type='adjustment', quantity=-1)
        StockMovement.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=8))

        response = self.client.get('/api/movements/?days=7')

        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['id'] for row in response.data], [recent.id])

    def test_stock_movement_history_rejects_unsupported_lookback(self):
        response = self.client.get('/api/movements/?days=3')

        self.assertEqual(response.status_code, 400)

    def test_stock_movement_history_filters_to_calendar_month(self):
        now = timezone.now()
        current = StockMovement.objects.create(product=self.product, movement_type='adjustment', quantity=1)
        previous = StockMovement.objects.create(product=self.product, movement_type='adjustment', quantity=-1)
        previous_month = now.replace(day=1) - timedelta(days=1)
        StockMovement.objects.filter(pk=previous.pk).update(created_at=previous_month)

        response = self.client.get(f'/api/movements/?month={now:%Y-%m}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['id'] for row in response.data], [current.id])

    def test_stock_movement_history_filters_to_selected_day(self):
        today = timezone.localdate()
        selected = StockMovement.objects.create(product=self.product, movement_type='adjustment', quantity=1)
        other = StockMovement.objects.create(product=self.product, movement_type='adjustment', quantity=-1)
        StockMovement.objects.filter(pk=other.pk).update(created_at=timezone.now() - timedelta(days=1))

        response = self.client.get(f'/api/movements/?date={today.isoformat()}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['id'] for row in response.data], [selected.id])

    def test_stock_movement_history_rejects_invalid_or_combined_date_filter(self):
        invalid = self.client.get('/api/movements/?date=2026-02-30')
        combined = self.client.get('/api/movements/?date=2026-02-28&days=7')

        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(combined.status_code, 400)

    def test_stock_movement_history_rejects_invalid_month(self):
        response = self.client.get('/api/movements/?month=2026-13')

        self.assertEqual(response.status_code, 400)

    def test_stock_count_records_the_signed_difference(self):
        response = self.client.post('/api/inventory/adjustments/', {
            'product': self.product.id,
            'adjustment_type': 'count',
            'counted_quantity': 7,
            'reason': 'Cycle count',
        }, format='json')

        self.assertEqual(response.status_code, 201)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 7)
        self.assertEqual(StockMovement.objects.get().quantity, -3)

    def test_adjustment_cannot_reduce_stock_below_zero(self):
        response = self.client.post('/api/inventory/adjustments/', {
            'product': self.product.id,
            'adjustment_type': 'decrease',
            'quantity': 11,
            'reason': 'Correction',
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 10)
        self.assertFalse(StockMovement.objects.exists())


class CustomerPOClientWorkflowTests(AdminAPITestCase):
    def setUp(self):
        super().setUp()
        self.customer = Customer.objects.create(customer_code='CPO-001', name='Bottle client')
        self.product = Product.objects.create(
            sku='BOTTLE-001',
            name='Waragi 750ml',
            category=Category.objects.create(name='Bottle inventory'),
            quantity=20,
            unit_price='150.00',
        )
        self.bottle = BottleProduct.objects.create(
            sku='BOTTLE-001',
            name='Waragi 750ml',
            category=BottleProduct.Category.UGANDA_WARAGI,
            quantity=20,
            unit_price='150.00',
            inventory_product=self.product,
        )
        self.material, _ = ClientMaterial.objects.get_or_create(
            material_type=ClientMaterial.MaterialType.SPENT_YEAST,
            defaults={'unit': 'kg', 'unit_price': '30.00'},
        )

    def test_bottle_po_supports_partial_deliveries_and_completes_on_fulfillment(self):
        created = self.client.post('/api/po-client/bottle-orders/', {
            'reference': 'CLIENT-BTL-001',
            'customer': self.customer.id,
            'items': [{'product': self.product.id, 'quantity': 12, 'unit_price': '150.00'}],
        }, format='json')

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data['total'], '1800.00')
        self.assertEqual(created.data['status'], BottleCustomerPO.Status.OPEN)
        self.assertEqual(created.data['items'][0]['product'], self.product.id)
        line_id = created.data['items'][0]['id']

        first_delivery = self.client.post(
            f"/api/po-client/bottle-orders/{created.data['id']}/deliver/",
            {'items': [{'purchase_order_line': line_id, 'quantity': 5}]},
            format='json',
        )
        self.assertEqual(first_delivery.status_code, 200)
        self.assertEqual(first_delivery.data['status'], BottleCustomerPO.Status.PARTIAL)
        self.assertEqual(first_delivery.data['items'][0]['delivered_quantity'], 5)
        self.assertEqual(first_delivery.data['items'][0]['remaining_quantity'], 7)
        self.assertEqual(len(first_delivery.data['deliveries']), 1)
        self.assertEqual(first_delivery.data['deliveries'][0]['items'][0]['quantity'], 5)
        self.bottle.refresh_from_db()
        self.assertEqual(self.bottle.quantity, 15)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 15)
        movement = StockMovement.objects.get()
        self.assertEqual(movement.product_id, self.product.id)
        self.assertEqual(movement.movement_type, StockMovement.MovementType.OUTBOUND)
        self.assertEqual(movement.quantity, 5)
        self.assertEqual(movement.reference, first_delivery.data['deliveries'][0]['reference'])
        inventory_product = self.client.get('/api/products/').data[0]
        self.assertEqual(inventory_product['id'], self.product.id)
        self.assertEqual(inventory_product['quantity'], 15)

        final_delivery = self.client.post(
            f"/api/po-client/bottle-orders/{created.data['id']}/deliver/",
            {'items': [{'purchase_order_line': line_id, 'quantity': 7}]},
            format='json',
        )
        self.assertEqual(final_delivery.status_code, 200)
        self.assertEqual(final_delivery.data['status'], BottleCustomerPO.Status.COMPLETED)
        self.assertEqual(
            sorted(delivery['items'][0]['quantity'] for delivery in final_delivery.data['deliveries']),
            [5, 7],
        )
        order_history = self.client.get('/api/po-client/bottle-orders/')
        self.assertEqual(order_history.status_code, 200)
        self.assertEqual(order_history.data[0]['status'], BottleCustomerPO.Status.COMPLETED)
        self.assertEqual(
            sorted(delivery['items'][0]['quantity'] for delivery in order_history.data[0]['deliveries']),
            [5, 7],
        )
        self.bottle.refresh_from_db()
        self.assertEqual(self.bottle.quantity, 8)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 8)
        self.assertEqual(StockMovement.objects.count(), 2)
        movements = self.client.get('/api/movements/').data
        self.assertEqual(len(movements), 2)
        self.assertTrue(all(row['product'] == self.product.id for row in movements))
        self.assertTrue(all(row['movement_type'] == StockMovement.MovementType.OUTBOUND for row in movements))
        customer_history = self.client.get(f'/api/customers/{self.customer.id}/dashboard/').data
        self.assertEqual(len(customer_history['bottle_purchase_orders']), 1)
        self.assertEqual(customer_history['bottle_purchase_orders'][0]['reference'], 'CLIENT-BTL-001')
        self.assertEqual(
            customer_history['bottle_purchase_orders'][0]['items'][0]['delivered_quantity'],
            12,
        )
        self.assertEqual(len(customer_history['bottle_purchase_orders'][0]['deliveries']), 2)
        self.assertEqual(customer_history['lifetime_revenue'], '0.00')
        self.assertEqual(customer_history['completed_orders'], 0)
        self.assertEqual(customer_history['outstanding_balance'], '0.00')

    def test_bottle_delivery_rejects_overdelivery_and_insufficient_stock_atomically(self):
        created = self.client.post('/api/po-client/bottle-orders/', {
            'reference': 'CLIENT-BTL-002',
            'customer': self.customer.id,
            'items': [{'product': self.product.id, 'quantity': 25, 'unit_price': '150.00'}],
        }, format='json')
        line_id = created.data['items'][0]['id']

        over_stock = self.client.post(
            f"/api/po-client/bottle-orders/{created.data['id']}/deliver/",
            {'items': [{'purchase_order_line': line_id, 'quantity': 21}]},
            format='json',
        )
        self.assertEqual(over_stock.status_code, 400)
        self.bottle.refresh_from_db()
        self.assertEqual(self.bottle.quantity, 20)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 20)
        self.assertFalse(StockMovement.objects.exists())

        delivered = self.client.post(
            f"/api/po-client/bottle-orders/{created.data['id']}/deliver/",
            {'items': [{'purchase_order_line': line_id, 'quantity': 12}]},
            format='json',
        )
        self.assertEqual(delivered.status_code, 200)
        over_order = self.client.post(
            f"/api/po-client/bottle-orders/{created.data['id']}/deliver/",
            {'items': [{'purchase_order_line': line_id, 'quantity': 14}]},
            format='json',
        )
        self.assertEqual(over_order.status_code, 400)
        self.bottle.refresh_from_db()
        self.assertEqual(self.bottle.quantity, 8)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 8)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_deleting_bottle_po_returns_all_delivered_stock(self):
        created = self.client.post('/api/po-client/bottle-orders/', {
            'reference': 'CLIENT-BTL-DELETE',
            'customer': self.customer.id,
            'items': [{'product': self.product.id, 'quantity': 12, 'unit_price': '150.00'}],
        }, format='json')
        line_id = created.data['items'][0]['id']

        for quantity in (3, 4):
            delivery = self.client.post(
                f"/api/po-client/bottle-orders/{created.data['id']}/deliver/",
                {'items': [{'purchase_order_line': line_id, 'quantity': quantity}]},
                format='json',
            )
            self.assertEqual(delivery.status_code, 200)

        deleted = self.client.delete(f"/api/po-client/bottle-orders/{created.data['id']}/")

        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(BottleCustomerPO.objects.filter(pk=created.data['id']).exists())
        self.assertFalse(BottleDelivery.objects.filter(purchase_order_id=created.data['id']).exists())
        self.product.refresh_from_db()
        self.bottle.refresh_from_db()
        self.assertEqual(self.product.quantity, 20)
        self.assertEqual(self.bottle.quantity, 20)
        return_movement = StockMovement.objects.get(
            movement_type=StockMovement.MovementType.RETURN,
            reference='CLIENT-BTL-DELETE-RETURN',
        )
        self.assertEqual(return_movement.product_id, self.product.id)
        self.assertEqual(return_movement.quantity, 7)

    def test_deleting_material_po_reverses_receipts_and_blocks_used_stock(self):
        created = self.client.post('/api/po-client/material-orders/', {
            'reference': 'CLIENT-SY-DELETE',
            'customer': self.customer.id,
            'material': self.material.id,
            'quantity': '20.00',
            'unit_price': '30.00',
        }, format='json')
        receipt = self.client.post(
            f"/api/po-client/material-orders/{created.data['id']}/receive/",
            {'quantity': '8.00'},
            format='json',
        )
        self.assertEqual(receipt.status_code, 200)

        self.material.quantity = Decimal('5.00')
        self.material.save(update_fields=['quantity'])
        blocked = self.client.delete(f"/api/po-client/material-orders/{created.data['id']}/")
        self.assertEqual(blocked.status_code, 400)
        self.assertTrue(ClientMaterialPO.objects.filter(pk=created.data['id']).exists())
        self.assertTrue(ClientMaterialReceipt.objects.filter(purchase_order_id=created.data['id']).exists())

        self.material.quantity = Decimal('10.00')
        self.material.save(update_fields=['quantity'])
        deleted = self.client.delete(f"/api/po-client/material-orders/{created.data['id']}/")
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(ClientMaterialPO.objects.filter(pk=created.data['id']).exists())
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('2.00'))

    def test_material_po_tracks_its_own_partial_receipts_and_rate(self):
        self.material.unit_price = Decimal('30.00')
        self.material.save(update_fields=['unit_price'])
        created = self.client.post('/api/po-client/material-orders/', {
            'reference': 'CLIENT-SY-001',
            'customer': self.customer.id,
            'material': self.material.id,
            'quantity': '100.00',
            'unit_price': '30.00',
        }, format='json')
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data['total'], '3000.00')
        self.assertEqual(created.data['status'], ClientMaterialPO.Status.OPEN)

        first_receipt = self.client.post(
            f"/api/po-client/material-orders/{created.data['id']}/receive/",
            {'quantity': '35.00'},
            format='json',
        )
        self.assertEqual(first_receipt.status_code, 200)
        self.assertEqual(first_receipt.data['status'], ClientMaterialPO.Status.PARTIAL)
        self.assertEqual(first_receipt.data['remaining_quantity'], Decimal('65.00'))
        self.assertEqual(len(first_receipt.data['receipts']), 1)
        customer_history = self.client.get(f'/api/customers/{self.customer.id}/dashboard/').data
        self.assertEqual(len(customer_history['client_material_purchase_orders']), 1)
        material_order = customer_history['client_material_purchase_orders'][0]
        self.assertEqual(material_order['reference'], 'CLIENT-SY-001')
        self.assertEqual(material_order['material_name'], self.material.name)
        self.assertEqual(material_order['receipts'][0]['quantity'], '35.00')

        excessive_receipt = self.client.post(
            f"/api/po-client/material-orders/{created.data['id']}/receive/",
            {'quantity': '66.00'},
            format='json',
        )
        self.assertEqual(excessive_receipt.status_code, 400)

        final_receipt = self.client.post(
            f"/api/po-client/material-orders/{created.data['id']}/receive/",
            {'quantity': '65.00'},
            format='json',
        )
        self.assertEqual(final_receipt.status_code, 200)
        self.assertEqual(final_receipt.data['status'], ClientMaterialPO.Status.COMPLETED)
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('100.00'))

    def test_custom_client_supplied_product_can_be_received_on_its_own_po(self):
        created_product = self.client.post('/api/po-client/materials/', {
            'name': 'Cooking Oil',
            'unit': 'litres',
            'unit_price': '5000.00',
        }, format='json')
        self.assertEqual(created_product.status_code, 201)
        self.assertEqual(created_product.data['name'], 'Cooking Oil')
        self.assertEqual(created_product.data['quantity'], '0.00')

        created_order = self.client.post('/api/po-client/material-orders/', {
            'reference': 'CLIENT-OIL-001',
            'customer': self.customer.id,
            'material': created_product.data['id'],
            'quantity': '20.00',
            'unit_price': '5000.00',
        }, format='json')
        self.assertEqual(created_order.status_code, 201)
        receipt = self.client.post(
            f"/api/po-client/material-orders/{created_order.data['id']}/receive/",
            {'quantity': '8.00'},
            format='json',
        )
        self.assertEqual(receipt.status_code, 200)
        self.assertEqual(receipt.data['material_name'], 'Cooking Oil')
        self.assertEqual(receipt.data['material_unit'], 'litres')
        created_product = self.client.get('/api/po-client/materials/').data
        oil = next(item for item in created_product if item['name'] == 'Cooking Oil')
        self.assertEqual(Decimal(oil['quantity']), Decimal('8.00'))

    def test_custom_delivery_product_tracks_its_stock_unit_and_partial_delivery(self):
        inventory_product = Product.objects.create(
            sku='BOX-001',
            name='Shipping Boxes',
            category=Category.objects.create(name='Packaging inventory'),
            quantity=10,
            unit_price='2000.00',
        )
        created_product = self.client.post('/api/po-client/bottle-products/', {
            'inventory_product': inventory_product.id,
            'category': 'Packaging',
            'unit': 'boxes',
            'unit_price': '2000.00',
        }, format='json')
        self.assertEqual(created_product.status_code, 201)
        product_id = created_product.data['id']
        self.assertEqual(product_id, inventory_product.id)
        listed_product = self.client.get('/api/po-client/bottle-products/').data[0]
        self.assertEqual(listed_product['id'], inventory_product.id)
        self.assertEqual(inventory_product.sku, 'BOX-001')
        self.assertEqual(inventory_product.quantity, 10)

        created_order = self.client.post('/api/po-client/bottle-orders/', {
            'reference': 'CLIENT-BOX-001',
            'customer': self.customer.id,
            'items': [{'product': created_product.data['id'], 'quantity': 6, 'unit_price': '2000.00'}],
        }, format='json')
        self.assertEqual(created_order.status_code, 201)
        line_id = created_order.data['items'][0]['id']
        delivery = self.client.post(
            f"/api/po-client/bottle-orders/{created_order.data['id']}/deliver/",
            {'items': [{'purchase_order_line': line_id, 'quantity': 2}]},
            format='json',
        )
        self.assertEqual(delivery.status_code, 200)
        self.assertEqual(delivery.data['items'][0]['unit'], 'boxes')
        self.assertEqual(delivery.data['items'][0]['product'], product_id)
        self.assertEqual(delivery.data['deliveries'][0]['items'][0]['unit'], 'boxes')
        self.assertEqual(delivery.data['items'][0]['remaining_quantity'], 4)
        inventory_product.refresh_from_db()
        self.assertEqual(inventory_product.quantity, 8)
        movement = StockMovement.objects.get(product=inventory_product)
        self.assertEqual(movement.movement_type, StockMovement.MovementType.OUTBOUND)
        self.assertEqual(movement.quantity, 2)


class PurchaseWorkflowTests(AdminAPITestCase):
    def setUp(self):
        super().setUp()
        category = Category.objects.create(name='Purchase inventory')
        self.supplier = Supplier.objects.create(name='Test supplier')
        self.product = Product.objects.create(
            sku='PO-001',
            name='Purchase product',
            category=category,
            supplier=self.supplier,
            quantity=4,
            reorder_level=2,
            unit_price='20.00',
            cost_price='8.00',
        )

    def create_purchase(self):
        return self.client.post('/api/purchases/', {
            'supplier': self.supplier.id,
            'notes': 'Restock order',
            'items': [{'product': self.product.id, 'quantity': 6, 'unit_cost': '9.25'}],
        }, format='json')

    def test_order_creation_does_not_change_stock(self):
        response = self.create_purchase()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], Purchase.Status.ORDERED)
        self.assertEqual(response.data['item_count'], 6)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 4)
        self.assertFalse(StockMovement.objects.exists())

    def test_receiving_adds_stock_once_and_records_inbound_movement(self):
        created = self.create_purchase()
        response = self.client.post(f"/api/purchases/{created.data['id']}/receive/", {}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], Purchase.Status.RECEIVED)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 10)
        self.assertEqual(self.product.cost_price, 9.25)
        movement = StockMovement.objects.get()
        self.assertEqual(movement.movement_type, StockMovement.MovementType.INBOUND)
        self.assertEqual(movement.quantity, 6)
        self.assertEqual(movement.reference, created.data['reference'])

        duplicate = self.client.post(f"/api/purchases/{created.data['id']}/receive/", {}, format='json')
        self.assertEqual(duplicate.status_code, 400)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 10)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_partial_and_full_purchase_payments_update_purchase_and_supplier_balances(self):
        created = self.create_purchase()
        purchase_id = created.data['id']
        self.client.post(f'/api/purchases/{purchase_id}/receive/', {}, format='json')

        partial = self.client.post(
            f'/api/purchases/{purchase_id}/payments/',
            {'amount': '20.00', 'payment_method': 'mobile', 'reference': 'BANK-001'},
            format='json',
        )

        self.assertEqual(partial.status_code, 201)
        self.assertEqual(partial.data['purchase']['payment_status'], 'partial')
        self.assertEqual(partial.data['purchase']['paid_amount'], '20.00')
        self.assertEqual(partial.data['purchase']['remaining_balance'], '35.50')
        self.assertEqual(partial.data['ledger_entry']['purchase_reference'], created.data['reference'])
        self.assertEqual(partial.data['ledger_entry']['payment_method'], 'mobile')
        self.assertEqual(partial.data['purchase']['payments'][0]['payment_method'], 'mobile')
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal('35.50'))

        full = self.client.post(
            f'/api/purchases/{purchase_id}/payments/',
            {'amount': '35.50', 'payment_method': 'card'},
            format='json',
        )

        self.assertEqual(full.status_code, 201)
        self.assertEqual(full.data['purchase']['payment_status'], 'paid')
        self.assertEqual(full.data['purchase']['paid_amount'], '55.50')
        self.assertEqual(full.data['purchase']['remaining_balance'], '0.00')
        self.assertCountEqual([payment['payment_method'] for payment in full.data['purchase']['payments']], ['mobile', 'card'])
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal('0.00'))

    def test_purchase_payment_cannot_be_recorded_before_receipt_or_exceed_balance(self):
        created = self.create_purchase()
        purchase_id = created.data['id']
        before_receipt = self.client.post(
            f'/api/purchases/{purchase_id}/payments/',
            {'amount': '1.00'},
            format='json',
        )
        self.assertEqual(before_receipt.status_code, 400)

        self.client.post(f'/api/purchases/{purchase_id}/receive/', {}, format='json')
        overpayment = self.client.post(
            f'/api/purchases/{purchase_id}/payments/',
            {'amount': '55.51'},
            format='json',
        )

        self.assertEqual(overpayment.status_code, 400)
        self.assertFalse(SupplierLedgerEntry.objects.filter(
            purchase_id=purchase_id,
            entry_type=SupplierLedgerEntry.EntryType.PAYMENT,
        ).exists())
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal('55.50'))


class PointOfSaleTests(AdminAPITestCase):
    def setUp(self):
        super().setUp()
        category = Category.objects.create(name='POS inventory')
        self.product = Product.objects.create(
            sku='POS-001',
            name='POS product',
            category=category,
            quantity=4,
            reorder_level=1,
            unit_price='10.00',
            cost_price='4.00',
        )
        self.customer = Customer.objects.create(
            customer_code='POS-CUST-001',
            name='POS customer',
            credit_limit='100.00',
        )

    def checkout(self, **overrides):
        payload = {
            'customer_name': 'Walk-in Customer',
            'payment_method': 'cash',
            'discount_percent': '10.00',
            'cash_tendered': '20.00',
            'items': [{'product': self.product.id, 'quantity': 2}],
        }
        payload.update(overrides)
        return self.client.post('/api/sales/checkout/', payload, format='json')

    def test_cash_checkout_records_totals_and_decrements_stock(self):
        response = self.checkout()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['subtotal'], '20.00')
        self.assertEqual(response.data['discount_amount'], '2.00')
        self.assertEqual(response.data['tax_amount'], '0.00')
        self.assertEqual(response.data['total'], '18.00')
        self.assertEqual(response.data['change_due'], '2.00')
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 2)
        self.assertEqual(Sale.objects.count(), 1)
        movement = StockMovement.objects.get()
        self.assertEqual(movement.movement_type, StockMovement.MovementType.OUTBOUND)
        self.assertEqual(movement.reference, response.data['receipt_number'])

    def test_checkout_accepts_a_customer_specific_unit_price(self):
        response = self.checkout(
            customer=self.customer.id,
            items=[{'product': self.product.id, 'quantity': 2, 'unit_price': '12.50'}],
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['subtotal'], '25.00')
        self.assertEqual(response.data['discount_amount'], '2.50')
        self.assertEqual(response.data['total'], '22.50')
        self.assertEqual(response.data['items'][0]['unit_price'], '12.50')
        self.assertEqual(response.data['items'][0]['line_total'], '25.00')
        self.product.refresh_from_db()
        self.assertEqual(self.product.unit_price, Decimal('10.00'))

    def test_checkout_rejects_invalid_unit_price_without_changing_stock(self):
        response = self.checkout(items=[{
            'product': self.product.id,
            'quantity': 2,
            'unit_price': '-1.00',
        }])

        self.assertEqual(response.status_code, 400)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 4)
        self.assertFalse(Sale.objects.exists())

    def test_overselling_rejects_checkout_without_partial_writes(self):
        response = self.checkout(items=[{'product': self.product.id, 'quantity': 5}])

        self.assertEqual(response.status_code, 400)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 4)
        self.assertFalse(Sale.objects.exists())
        self.assertFalse(StockMovement.objects.exists())

    def test_cash_underpayment_is_rejected(self):
        response = self.checkout(cash_tendered='17.00')

        self.assertEqual(response.status_code, 400)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 4)
        self.assertFalse(Sale.objects.exists())

    def test_partial_cash_payment_records_remaining_customer_balance(self):
        response = self.checkout(customer=self.customer.id, cash_tendered='10.00')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['payment_method'], Sale.PaymentMethod.CASH)
        self.assertEqual(response.data['cash_tendered'], '10.00')
        self.assertEqual(response.data['paid_amount'], '10.00')
        self.assertEqual(response.data['remaining_balance'], '8.00')
        self.assertEqual(response.data['payment_status'], 'partial')
        self.customer.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.customer.outstanding_balance, Decimal('8.00'))
        self.assertEqual(self.product.quantity, 2)
        self.assertEqual(
            CustomerLedgerEntry.objects.filter(customer=self.customer, entry_type=CustomerLedgerEntry.EntryType.CHARGE).get().amount,
            Decimal('18.00'),
        )
        self.assertEqual(
            CustomerLedgerEntry.objects.filter(customer=self.customer, entry_type=CustomerLedgerEntry.EntryType.PAYMENT).get().amount,
            Decimal('10.00'),
        )

        dashboard = self.client.get(f'/api/customers/{self.customer.id}/dashboard/').data
        self.assertEqual(dashboard['outstanding_balance'], '8.00')
        self.assertEqual(dashboard['total_paid_amount'], '10.00')
        self.assertEqual(dashboard['total_remaining_balance'], '8.00')
        self.assertEqual(dashboard['sales'][0]['remaining_balance'], '8.00')

        payment = self.client.post(f'/api/customers/{self.customer.id}/payments/', {
            'amount': '8.00',
            'sale': response.data['id'],
        }, format='json')
        self.assertEqual(payment.status_code, 201)
        dashboard = self.client.get(f'/api/customers/{self.customer.id}/dashboard/').data
        self.assertEqual(dashboard['outstanding_balance'], '0.00')
        self.assertEqual(dashboard['total_paid_amount'], '18.00')
        self.assertEqual(dashboard['total_remaining_balance'], '0.00')

    def test_completed_sale_uses_discounted_price_snapshots_in_dashboard(self):
        checkout_response = self.checkout()
        self.assertEqual(checkout_response.status_code, 201)

        summary = self.client.get('/api/dashboard/summary/').data

        self.assertEqual(summary['today_sales'], '18.00')
        self.assertEqual(summary['period_sales'], '18.00')
        self.assertEqual(summary['gross_profit'], '10.00')
        self.assertAlmostEqual(sum(day['sales'] for day in summary['series']), 18.0)


class ReportsDashboardTests(AdminAPITestCase):
    def setUp(self):
        super().setUp()
        category = Category.objects.create(name='Report category')
        supplier = Supplier.objects.create(name='Report supplier')
        self.product = Product.objects.create(
            sku='RPT-001',
            name='Report product',
            category=category,
            supplier=supplier,
            quantity=8,
            reorder_level=2,
            unit_price='10.00',
            cost_price='4.00',
        )
        sale = Sale.objects.create(
            receipt_number='SALE-REPORT-001',
            customer_name='Walk-in Customer',
            payment_method=Sale.PaymentMethod.CARD,
            subtotal='20.00',
            discount_percent='10.00',
            discount_amount='2.00',
            tax_rate='8.50',
            tax_amount='1.53',
            total='19.53',
        )
        SaleItem.objects.create(
            sale=sale,
            product=self.product,
            product_name=self.product.name,
            product_sku=self.product.sku,
            quantity=2,
            unit_price='10.00',
            unit_cost='4.00',
        )
        purchase = Purchase.objects.create(reference='PO-REPORT-001', supplier=supplier, status=Purchase.Status.RECEIVED, received_at=timezone.now())
        PurchaseItem.objects.create(purchase=purchase, product=self.product, quantity=3, unit_cost='4.00')

    def test_report_summary_returns_sales_inventory_purchase_and_product_breakdowns(self):
        response = self.client.get('/api/reports/summary/?range=30d')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['revenue'], '18.00')
        self.assertEqual(response.data['cost_of_goods'], '8.00')
        self.assertEqual(response.data['gross_profit'], '10.00')
        self.assertEqual(response.data['inventory_value'], '32.00')
        self.assertEqual(response.data['purchase_spend'], '12.00')
        self.assertEqual(response.data['categories'][0]['name'], 'Report category')
        self.assertEqual(response.data['inventory_categories'][0]['units'], 8)
        self.assertEqual(response.data['top_products'][0]['units_sold'], 2)
        self.assertEqual(len(response.data['daily_series']), 30)
        self.assertEqual(response.data['daily_series'][-1]['cost_of_goods'], 8.0)
        self.assertEqual(response.data['daily_series'][-1]['gross_profit'], 10.0)
        self.assertEqual(response.data['daily_series'][-1]['net_profit'], 10.0)

    def test_report_range_is_bounded_to_supported_periods(self):
        for value, days in [
            ('1d', 1), ('7d', 7), ('30d', 30), ('90d', 90), ('180d', 180), ('365d', 365),
            ('730d', 730), ('1825d', 1825), ('3650d', 3650), ('18250d', 18250),
            ('36500d', 36500), ('73000d', 73000),
        ]:
            with self.subTest(value=value):
                response = self.client.get(f'/api/reports/summary/?range={value}')
                self.assertEqual(response.data['range_days'], days)
                if days <= 365:
                    self.assertEqual(len(response.data['daily_series']), days)
                    self.assertEqual(response.data['series_interval'], 'day')
                else:
                    self.assertLessEqual(len(response.data['daily_series']), 201)
                    self.assertEqual(response.data['series_interval'], 'month' if days <= 3650 else 'year')

        fallback = self.client.get('/api/reports/summary/?range=bad')
        self.assertEqual(fallback.data['range_days'], 30)

    def test_report_summary_filters_to_selected_calendar_month(self):
        today = timezone.localdate()
        month = today.strftime('%Y-%m')
        response = self.client.get(f'/api/reports/summary/?month={month}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['start_date'], today.replace(day=1).isoformat())
        self.assertEqual(response.data['revenue'], '18.00')
        self.assertEqual(response.data['purchase_spend'], '12.00')

    def test_report_summary_filters_to_selected_day(self):
        selected_day = timezone.localdate() - timedelta(days=1)
        Sale.objects.filter(receipt_number='SALE-REPORT-001').update(
            created_at=timezone.now() - timedelta(days=2),
        )

        response = self.client.get(f'/api/reports/summary/?date={selected_day.isoformat()}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['start_date'], selected_day.isoformat())
        self.assertEqual(response.data['end_date'], selected_day.isoformat())
        self.assertEqual(response.data['range_days'], 1)
        self.assertEqual(response.data['revenue'], '0.00')

    def test_report_summary_rejects_invalid_selected_day(self):
        response = self.client.get('/api/reports/summary/?date=2026-02-30')

        self.assertEqual(response.status_code, 400)

    def test_report_summary_rejects_invalid_calendar_month(self):
        response = self.client.get('/api/reports/summary/?month=2026-13')

        self.assertEqual(response.status_code, 400)


class CustomerAccountTests(AdminAPITestCase):
    def setUp(self):
        super().setUp()
        category = Category.objects.create(name='Customer account inventory')
        self.product = Product.objects.create(
            sku='CUS-001',
            name='Customer account product',
            category=category,
            quantity=5,
            reorder_level=1,
            unit_price='10.00',
            cost_price='4.00',
        )
        self.customer = Customer.objects.create(
            customer_code='CUST-TEST1',
            name='Acme Industrial',
            contact_name='Riley Jones',
            email='riley@example.test',
            credit_limit='100.00',
        )

    def test_customer_list_uses_bounded_aggregate_queries(self):
        with CaptureQueriesContext(connection) as initial_queries:
            initial_response = self.client.get('/api/customers/')
        self.assertEqual(initial_response.status_code, 200)

        for index in range(5):
            Customer.objects.create(
                customer_code=f'CUST-Q{index}',
                name=f'Query Customer {index}',
            )

        with CaptureQueriesContext(connection) as expanded_queries:
            response = self.client.get('/api/customers/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 6)
        self.assertLessEqual(len(expanded_queries), len(initial_queries) + 1)

    def test_on_account_sale_updates_customer_history_balance_and_stock(self):
        response = self.client.post('/api/sales/checkout/', {
            'customer': self.customer.id,
            'payment_method': 'account',
            'discount_percent': '0',
            'items': [{'product': self.product.id, 'quantity': 2}],
        }, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['customer'], self.customer.id)
        self.assertEqual(response.data['customer_name'], 'Acme Industrial')
        self.customer.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.customer.outstanding_balance, Decimal('20.00'))
        self.assertEqual(self.product.quantity, 3)
        charge = CustomerLedgerEntry.objects.get(entry_type=CustomerLedgerEntry.EntryType.CHARGE)
        self.assertEqual(charge.reference, response.data['receipt_number'])

        payment = self.client.post(f'/api/customers/{self.customer.id}/payments/', {
            'amount': '5.00',
            'payment_method': 'mobile',
            'reference': 'PAY-001',
            'note': 'ACH payment',
        }, format='json')
        self.assertEqual(payment.status_code, 201)
        self.assertEqual(payment.data['ledger_entry']['payment_method'], 'mobile')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.outstanding_balance, Decimal('15.00'))
        self.assertEqual(CustomerLedgerEntry.objects.count(), 2)

        dashboard = self.client.get(f'/api/customers/{self.customer.id}/dashboard/').data
        self.assertEqual(dashboard['completed_orders'], 1)
        self.assertEqual(dashboard['lifetime_revenue'], '20.00')
        self.assertEqual(dashboard['outstanding_balance'], '15.00')
        self.assertEqual(dashboard['total_paid_amount'], '5.00')
        self.assertEqual(dashboard['total_remaining_balance'], '15.00')
        self.assertEqual(dashboard['account_charges'], '20.00')
        self.assertEqual(dashboard['account_payments'], '5.00')
        self.assertEqual(dashboard['account_credits'], '0.00')
        self.assertEqual(len(dashboard['sales']), 1)
        self.assertEqual(dashboard['sales'][0]['paid_amount'], '5.00')
        self.assertEqual(dashboard['sales'][0]['remaining_balance'], '15.00')
        self.assertEqual(dashboard['sales'][0]['payment_status'], 'partial')
        self.assertEqual(dashboard['sales'][0]['payments'][0]['payment_method'], 'mobile')
        self.assertEqual(dashboard['sales'][0]['items'][0]['product_name'], self.product.name)
        self.assertEqual(dashboard['sales'][0]['items'][0]['line_total'], '20.00')
        self.assertEqual(len(dashboard['ledger_entries']), 2)

        full_payment = self.client.post(f'/api/customers/{self.customer.id}/payments/', {
            'amount': '15.00',
            'reference': 'PAY-002',
        }, format='json')
        self.assertEqual(full_payment.status_code, 201)
        dashboard = self.client.get(f'/api/customers/{self.customer.id}/dashboard/').data
        self.assertEqual(dashboard['outstanding_balance'], '0.00')
        self.assertEqual(dashboard['total_paid_amount'], '20.00')
        self.assertEqual(dashboard['total_remaining_balance'], '0.00')
        self.assertEqual(dashboard['account_payments'], '20.00')
        self.assertEqual(dashboard['sales'][0]['paid_amount'], '20.00')
        self.assertEqual(dashboard['sales'][0]['remaining_balance'], '0.00')

    def test_dashboard_payment_totals_include_immediate_and_partial_sales(self):
        cash_sale = self.client.post('/api/sales/checkout/', {
            'customer': self.customer.id,
            'payment_method': 'cash',
            'cash_tendered': '10.00',
            'items': [{'product': self.product.id, 'quantity': 1}],
        }, format='json')
        account_sale = self.client.post('/api/sales/checkout/', {
            'customer': self.customer.id,
            'payment_method': 'account',
            'items': [{'product': self.product.id, 'quantity': 2}],
        }, format='json')
        self.assertEqual(cash_sale.status_code, 201)
        self.assertEqual(account_sale.status_code, 201)

        payment = self.client.post(f'/api/customers/{self.customer.id}/payments/', {
            'amount': '5.00',
            'sale': account_sale.data['id'],
        }, format='json')
        self.assertEqual(payment.status_code, 201)

        dashboard = self.client.get(f'/api/customers/{self.customer.id}/dashboard/').data
        self.assertEqual(dashboard['lifetime_revenue'], '30.00')
        self.assertEqual(dashboard['total_paid_amount'], '15.00')
        self.assertEqual(dashboard['total_remaining_balance'], '15.00')

    def test_customer_payments_are_allocated_to_oldest_outstanding_sale_first(self):
        create_account_sale = lambda: self.client.post('/api/sales/checkout/', {
            'customer': self.customer.id,
            'payment_method': 'account',
            'items': [{'product': self.product.id, 'quantity': 1}],
        }, format='json')
        older_sale = create_account_sale()
        newer_sale = create_account_sale()
        self.assertEqual(older_sale.status_code, 201)
        self.assertEqual(newer_sale.status_code, 201)

        payment = self.client.post(f'/api/customers/{self.customer.id}/payments/', {
            'amount': '15.00',
            'reference': 'PAY-FIFO',
        }, format='json')

        self.assertEqual(payment.status_code, 201)
        self.assertEqual(len(payment.data['ledger_entries']), 2)
        dashboard = self.client.get(f'/api/customers/{self.customer.id}/dashboard/').data
        sales_by_reference = {sale['receipt_number']: sale for sale in dashboard['sales']}
        self.assertEqual(sales_by_reference[older_sale.data['receipt_number']]['paid_amount'], '10.00')
        self.assertEqual(sales_by_reference[older_sale.data['receipt_number']]['remaining_balance'], '0.00')
        self.assertEqual(sales_by_reference[newer_sale.data['receipt_number']]['paid_amount'], '5.00')
        self.assertEqual(sales_by_reference[newer_sale.data['receipt_number']]['remaining_balance'], '5.00')

    def test_customer_payment_can_be_confirmed_against_a_specific_sale(self):
        create_account_sale = lambda: self.client.post('/api/sales/checkout/', {
            'customer': self.customer.id,
            'payment_method': 'account',
            'items': [{'product': self.product.id, 'quantity': 1}],
        }, format='json')
        older_sale = create_account_sale()
        selected_sale = create_account_sale()
        self.assertEqual(older_sale.status_code, 201)
        self.assertEqual(selected_sale.status_code, 201)

        payment = self.client.post(f'/api/customers/{self.customer.id}/payments/', {
            'amount': '5.00',
            'sale': selected_sale.data['id'],
            'reference': 'PAY-INVOICE',
        }, format='json')

        self.assertEqual(payment.status_code, 201)
        self.assertEqual(payment.data['ledger_entry']['sale_reference'], selected_sale.data['receipt_number'])
        dashboard = self.client.get(f'/api/customers/{self.customer.id}/dashboard/').data
        sales_by_reference = {sale['receipt_number']: sale for sale in dashboard['sales']}
        self.assertEqual(sales_by_reference[older_sale.data['receipt_number']]['paid_amount'], '0.00')
        self.assertEqual(sales_by_reference[older_sale.data['receipt_number']]['remaining_balance'], '10.00')
        self.assertEqual(sales_by_reference[selected_sale.data['receipt_number']]['paid_amount'], '5.00')
        self.assertEqual(sales_by_reference[selected_sale.data['receipt_number']]['remaining_balance'], '5.00')

        wrong_customer_sale = Sale.objects.create(
            receipt_number='OTHER-CUSTOMER-SALE',
            customer=Customer.objects.create(customer_code='CUST-OTHER', name='Other customer'),
            customer_name='Other customer',
            payment_method=Sale.PaymentMethod.ACCOUNT,
            subtotal='10.00',
            discount_amount='0.00',
            tax_rate='0.00',
            tax_amount='0.00',
            total='10.00',
        )
        invalid_payment = self.client.post(f'/api/customers/{self.customer.id}/payments/', {
            'amount': '1.00',
            'sale': wrong_customer_sale.id,
        }, format='json')
        self.assertEqual(invalid_payment.status_code, 400)

    def test_customer_credit_limit_rejects_sale_without_partial_changes(self):
        self.customer.credit_limit = Decimal('10.00')
        self.customer.save(update_fields=['credit_limit'])
        response = self.client.post('/api/sales/checkout/', {
            'customer': self.customer.id,
            'payment_method': 'account',
            'items': [{'product': self.product.id, 'quantity': 2}],
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.customer.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.customer.outstanding_balance, Decimal('0'))
        self.assertEqual(self.product.quantity, 5)
        self.assertFalse(Sale.objects.exists())

    def test_sales_tax_rate_is_zero_even_for_tax_exempt_customer(self):
        self.customer.tax_exempt = True
        self.customer.save(update_fields=['tax_exempt'])
        response = self.client.post('/api/sales/checkout/', {
            'customer': self.customer.id,
            'payment_method': 'card',
            'items': [{'product': self.product.id, 'quantity': 1}],
        }, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['tax_rate'], '0.00')
        self.assertEqual(response.data['tax_amount'], '0.00')
        self.assertEqual(response.data['total'], '10.00')

    def test_customer_api_does_not_allow_tax_exemption(self):
        response = self.client.patch(
            f'/api/customers/{self.customer.id}/',
            {'tax_exempt': True},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['tax_exempt'])
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.tax_exempt)

    def test_customer_creation_assigns_unique_code(self):
        response = self.client.post('/api/customers/', {
            'name': 'Northwind Manufacturing',
            'email': 'accounts@example.test',
            'sector': 'Industrial supply',
            'tier': 'growth',
            'credit_limit': '2500.00',
        }, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['customer_code'].startswith('CUST-'))
        self.assertEqual(response.data['name'], 'Northwind Manufacturing')


class SupplierAccountTests(AdminAPITestCase):
    def setUp(self):
        super().setUp()
        category = Category.objects.create(name='Supplier dashboard inventory')
        self.supplier = Supplier.objects.create(
            name='Steelcraft Industries',
            contact_name='Morgan Lee',
            email='morgan@example.test',
            sector='Industrial supply',
            payment_terms='Net 30',
        )
        self.product = Product.objects.create(
            sku='SUP-001',
            name='Supplier test product',
            category=category,
            supplier=self.supplier,
            quantity=0,
            reorder_level=1,
            unit_price='25.00',
            cost_price='8.00',
        )

    def create_and_receive_purchase(self):
        created = self.client.post('/api/purchases/', {
            'supplier': self.supplier.id,
            'expected_delivery': '2026-09-01',
            'items': [{'product': self.product.id, 'quantity': 3, 'unit_cost': '8.50'}],
        }, format='json')
        self.assertEqual(created.status_code, 201)
        received = self.client.post(f"/api/purchases/{created.data['id']}/receive/", {}, format='json')
        self.assertEqual(received.status_code, 200)
        return created

    def test_received_purchase_updates_payable_and_supplier_dashboard(self):
        created = self.create_and_receive_purchase()

        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal('25.50'))
        charge = SupplierLedgerEntry.objects.get(entry_type=SupplierLedgerEntry.EntryType.CHARGE)
        self.assertEqual(charge.purchase.reference, created.data['reference'])
        self.assertEqual(charge.amount, Decimal('25.50'))

        dashboard = self.client.get(f'/api/suppliers/{self.supplier.id}/dashboard/').data
        self.assertEqual(dashboard['supplier']['supplier_code'], self.supplier.supplier_code)
        self.assertEqual(dashboard['lifetime_spend'], '25.50')
        self.assertEqual(dashboard['outstanding_balance'], '25.50')
        self.assertEqual(dashboard['received_orders'], 1)
        self.assertEqual(len(dashboard['purchase_orders']), 1)
        self.assertEqual(dashboard['purchase_orders'][0]['expected_delivery'], '2026-09-01')
        self.assertEqual(dashboard['supplier']['on_time_delivery_rate'], 0)
        self.assertEqual(len(dashboard['ledger_entries']), 1)
        self.assertEqual(len(dashboard['supplied_products']), 1)

    def test_supplier_payment_reduces_balance_and_rejects_overpayment(self):
        self.create_and_receive_purchase()
        payment = self.client.post(f'/api/suppliers/{self.supplier.id}/payments/', {
            'amount': '10.00',
            'reference': 'WIRE-001',
            'note': 'Net 30 remittance',
        }, format='json')

        self.assertEqual(payment.status_code, 201)
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal('15.50'))
        self.assertEqual(SupplierLedgerEntry.objects.count(), 2)

        overpayment = self.client.post(f'/api/suppliers/{self.supplier.id}/payments/', {
            'amount': '20.00',
        }, format='json')
        self.assertEqual(overpayment.status_code, 400)
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.outstanding_balance, Decimal('15.50'))

    def test_supplier_creation_generates_a_unique_code(self):
        response = self.client.post('/api/suppliers/', {
            'name': 'Northstar Components',
            'email': 'orders@example.test',
            'lead_time_days': 12,
        }, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['supplier_code'].startswith('SUP-'))


class ExpenseDashboardTests(AdminAPITestCase):
    def create_expense(self, **overrides):
        payload = {
            'merchant': 'Apex Freight Logistics',
            'description': 'Pallet delivery and handling',
            'category': 'Logistics & Freight',
            'cost_center': 'Warehouse & Logistics',
            'expense_type': 'freight',
            'amount_before_tax': '100.00',
            'tax_amount': '8.00',
            'payment_method': 'bank',
            'status': 'pending',
            'reference': 'INV-EXP-001',
            'receipt_received': True,
            'receipt_verified': True,
        }
        payload.update(overrides)
        return self.client.post('/api/expenses/', payload, format='json')

    def test_expense_creation_summary_and_budget_guardrail(self):
        pending = self.create_expense()
        paid = self.create_expense(
            merchant='Northstar Utilities',
            description='Monthly power bill',
            category='Utilities & Cloud',
            amount_before_tax='200.00',
            tax_amount='10.00',
            status='paid',
            receipt_verified=False,
            reference='INV-EXP-002',
        )
        self.assertEqual(pending.status_code, 201)
        self.assertEqual(pending.data['total_amount'], '108.00')
        self.assertTrue(pending.data['expense_number'].startswith('EXP-'))
        self.assertEqual(paid.data['total_amount'], '210.00')

        budget = self.client.post('/api/expense-budgets/', {
            'category': 'Logistics & Freight',
            'monthly_limit': '90.00',
            'cost_center': 'Warehouse & Logistics',
            'manager': 'Elena Vance',
        }, format='json')
        self.assertEqual(budget.status_code, 201)

        summary = self.client.get('/api/expenses/summary/').data
        self.assertTrue(summary['can_edit_expenses'])
        self.assertEqual(summary['total_expenses'], '318.00')
        self.assertEqual(summary['pending_approval'], '108.00')
        self.assertEqual(summary['pending_count'], 1)
        self.assertEqual(summary['tax_reclaimable'], '8.00')
        self.assertEqual(summary['verified_receipts'], 1)
        self.assertEqual(summary['largest_category']['name'], 'Utilities & Cloud')
        logistics_budget = next(item for item in summary['budgets'] if item['category'] == 'Logistics & Freight')
        self.assertEqual(logistics_budget['percent_used'], 120.0)
        self.assertEqual(len(summary['expenses']), 2)

    def test_expense_can_be_edited_and_recalculates_total(self):
        created = self.create_expense()

        response = self.client.patch(f"/api/expenses/{created.data['id']}/", {
            'merchant': 'Updated Freight Company',
            'amount_before_tax': '125.00',
            'tax_amount': '10.00',
            'receipt_verified': False,
        }, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['merchant'], 'Updated Freight Company')
        self.assertEqual(response.data['amount_before_tax'], '125.00')
        self.assertEqual(response.data['tax_amount'], '10.00')
        self.assertEqual(response.data['total_amount'], '135.00')
        self.assertFalse(response.data['receipt_verified'])

    def test_expense_can_be_edited_after_its_options_are_removed(self):
        created = self.create_expense()
        ExpenseCategory.objects.filter(name='Logistics & Freight').delete()
        ExpenseTypeOption.objects.filter(value='freight').delete()

        response = self.client.patch(f"/api/expenses/{created.data['id']}/", {
            'description': 'Updated delivery service',
        }, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['description'], 'Updated delivery service')
        self.assertEqual(response.data['category'], 'Logistics & Freight')
        self.assertEqual(response.data['expense_type'], 'freight')

    def test_expense_summary_hides_edit_actions_without_change_permission(self):
        user = get_user_model().objects.create_user(
            username='expense-viewer',
            password='test-password',
            is_staff=True,
        )
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label='inventory', codename='view_expense'),
            Permission.objects.get(content_type__app_label='inventory', codename='view_expensebudget'),
        )
        self.client.force_authenticate(user=user)

        summary = self.client.get('/api/expenses/summary/')

        self.assertEqual(summary.status_code, 200)
        self.assertFalse(summary.data['can_edit_expenses'])

    def test_expense_summary_query_count_does_not_scale_with_budgets(self):
        self.create_expense()
        ExpenseBudget.objects.create(category='Performance 0', monthly_limit='100.00')
        with CaptureQueriesContext(connection) as initial_queries:
            initial_response = self.client.get('/api/expenses/summary/')
        self.assertEqual(initial_response.status_code, 200)

        for index in range(1, 10):
            ExpenseBudget.objects.create(category=f'Performance {index}', monthly_limit='100.00')

        with CaptureQueriesContext(connection) as expanded_queries:
            response = self.client.get('/api/expenses/summary/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['budgets']), 10)
        self.assertLessEqual(len(expanded_queries), len(initial_queries) + 1)

    def test_expense_categories_and_types_can_be_added_and_used(self):
        created_category = self.client.post('/api/expense-options/', {
            'kind': 'category',
            'name': 'Staff Travel',
        }, format='json')
        self.assertEqual(created_category.status_code, 201)
        self.assertIn('Staff Travel', [item['name'] for item in created_category.data['categories']])

        created_type = self.client.post('/api/expense-options/', {
            'kind': 'type',
            'name': 'Staff Travel',
        }, format='json')
        self.assertEqual(created_type.status_code, 201)
        travel_type = next(item for item in created_type.data['types'] if item['label'] == 'Staff Travel')
        self.assertEqual(travel_type['value'], 'staff-travel')

        expense = self.create_expense(
            category='Staff Travel',
            expense_type=travel_type['value'],
        )
        self.assertEqual(expense.status_code, 201)
        self.assertEqual(expense.data['category'], 'Staff Travel')
        self.assertEqual(expense.data['expense_type'], 'staff-travel')

        summary = self.client.get('/api/expenses/summary/').data
        self.assertIn(travel_type, summary['expense_types'])
        self.assertEqual(
            sum(day['types'].get('staff-travel', 0) for day in summary['daily_series']),
            108.0,
        )

    def test_duplicate_expense_categories_and_types_are_rejected(self):
        for payload in (
            {'kind': 'category', 'name': 'utilities & cloud'},
            {'kind': 'type', 'name': 'operational'},
        ):
            with self.subTest(payload=payload):
                response = self.client.post('/api/expense-options/', payload, format='json')
                self.assertEqual(response.status_code, 400)

    def test_expense_category_can_be_removed_without_deleting_historical_records(self):
        created = self.client.post('/api/expense-options/', {
            'kind': 'category',
            'name': 'Staff Travel',
        }, format='json')
        category = next(item for item in created.data['categories'] if item['name'] == 'Staff Travel')
        expense = self.create_expense(category='Staff Travel')
        budget = self.client.post('/api/expense-budgets/', {
            'category': 'Staff Travel',
            'monthly_limit': '500.00',
            'cost_center': 'People',
            'manager': 'Elena Vance',
        }, format='json')

        self.assertEqual(expense.status_code, 201)
        self.assertEqual(budget.status_code, 201)
        deleted = self.client.delete(f"/api/expense-options/categories/{category['id']}/")

        self.assertEqual(deleted.status_code, 200)
        self.assertNotIn('Staff Travel', [item['name'] for item in deleted.data['categories']])
        self.assertTrue(Expense.objects.filter(category='Staff Travel').exists())
        self.assertTrue(ExpenseBudget.objects.filter(category='Staff Travel').exists())

    def test_expense_type_can_be_removed_without_deleting_historical_records(self):
        created = self.client.post('/api/expense-options/', {
            'kind': 'type',
            'name': 'Staff Travel',
        }, format='json')
        expense_type = next(item for item in created.data['types'] if item['label'] == 'Staff Travel')
        expense = self.create_expense(expense_type=expense_type['value'])

        self.assertEqual(expense.status_code, 201)
        deleted = self.client.delete(f"/api/expense-options/types/{expense_type['id']}/")

        self.assertEqual(deleted.status_code, 200)
        self.assertNotIn(expense_type['value'], [item['value'] for item in deleted.data['types']])
        self.assertTrue(Expense.objects.filter(expense_type=expense_type['value']).exists())

    def test_expense_requires_a_configured_category_and_type(self):
        response = self.create_expense(category='Unconfigured', expense_type='unconfigured')

        self.assertEqual(response.status_code, 400)
        self.assertIn('category', response.data)
        self.assertIn('expense_type', response.data)

    def test_bulk_upload_is_atomic_when_a_row_is_invalid(self):
        response = self.client.post('/api/expenses/bulk-upload/', {
            'expenses': [
                {'merchant': 'Valid Merchant', 'description': 'Valid line', 'category': 'Facilities', 'amount_before_tax': '25.00', 'tax_amount': '0.00', 'payment_method': 'cash'},
                {'merchant': 'Invalid Merchant', 'description': 'Negative amount', 'category': 'Facilities', 'amount_before_tax': '-5.00', 'tax_amount': '0.00', 'payment_method': 'cash'},
            ],
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Expense.objects.exists())

    def test_approved_and_paid_expenses_reduce_financial_net_profit(self):
        self.create_expense(status='pending')
        self.create_expense(status='approved', merchant='Approved Maintenance', amount_before_tax='40.00', tax_amount='0.00')

        report = self.client.get('/api/reports/summary/?range=30d').data

        self.assertEqual(report['operating_expenses'], '40.00')
        self.assertEqual(report['net_profit'], '-40.00')
        self.assertEqual(report['daily_series'][-1]['net_profit'], -40.0)

    def test_balance_sheet_combines_tracked_balances_and_manual_accounts(self):
        category = Category.objects.create(name='Balance sheet stock')
        Product.objects.create(
            sku='BS-INV-001',
            name='Balance sheet stock',
            category=category,
            quantity=5,
            unit_price='10.00',
            cost_price='4.00',
        )
        Customer.objects.create(customer_code='CUST-BS-001', name='Balance sheet customer', outstanding_balance='30.00')
        Supplier.objects.create(name='Balance sheet supplier', outstanding_balance='40.00')
        self.create_expense(status='approved', amount_before_tax='10.00', tax_amount='0.00')
        incomplete_sheet = self.client.get('/api/expenses/balance-sheet/').data
        self.assertFalse(incomplete_sheet['current_complete'])
        self.assertFalse(incomplete_sheet['is_balanced'])
        self.assertFalse(incomplete_sheet['prior_complete'])
        self.assertFalse(incomplete_sheet['is_prior_balanced'])
        BalanceSheetAccount.objects.update(amount='0.00', prior_amount='0.00')
        manual_accounts = [
            ('cash_and_cash_equivalents', {'amount': '50.00', 'prior_amount': '10.00'}),
            ('noncurrent_term_debt', {'amount': '20.00', 'prior_amount': '0.00'}),
            ('common_stock_and_additional_paid_in_capital', {'amount': '30.00', 'prior_amount': '15.00'}),
            ('accounts_receivable_net', {'amount': '0.00', 'prior_amount': '2.00'}),
            ('inventories', {'amount': '0.00', 'prior_amount': '8.00'}),
            ('accounts_payable', {'amount': '0.00', 'prior_amount': '4.00'}),
            ('other_current_liabilities', {'amount': '0.00', 'prior_amount': '1.00'}),
        ]
        for category, balances in manual_accounts:
            response = self.client.patch(f'/api/balance-sheet-accounts/{category}/', balances, format='json')
            self.assertEqual(response.status_code, 200)

        response = self.client.get('/api/expenses/balance-sheet/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['current_year'], timezone.localdate().year)
        self.assertEqual(response.data['prior_year'], timezone.localdate().year - 1)
        self.assertEqual(response.data['total_assets'], '100.00')
        self.assertEqual(response.data['total_liabilities'], '70.00')
        self.assertEqual(response.data['total_equity'], '30.00')
        self.assertEqual(response.data['difference'], '0.00')
        self.assertTrue(response.data['is_balanced'])
        self.assertTrue(response.data['current_complete'])
        self.assertEqual(response.data['assets']['prior_total'], '20.00')
        self.assertEqual(response.data['liabilities']['prior_total'], '5.00')
        self.assertEqual(response.data['equity']['prior_total'], '15.00')
        self.assertEqual(response.data['prior_difference'], '0.00')
        self.assertTrue(response.data['is_prior_balanced'])
        self.assertTrue(response.data['prior_complete'])
        self.assertEqual(response.data['as_of_date'], timezone.localdate().isoformat())
        self.assertEqual(
            next(
                row['current_amount']
                for group in response.data['liabilities']['groups']
                for row in group['rows']
                if row['category'] == 'other_current_liabilities'
            ),
            '10.00',
        )
        all_rows = [
            row
            for section in ('assets', 'liabilities', 'equity')
            for group in response.data[section]['groups']
            for row in group['rows']
        ]
        self.assertEqual(len(all_rows), 19)
        self.assertEqual(len({row['category'] for row in all_rows}), 19)

        negative_equity = self.client.patch(
            '/api/balance-sheet-accounts/accumulated_other_comprehensive_income_loss/',
            {'amount': '-5.00', 'prior_amount': '-406.00'},
            format='json',
        )
        self.assertEqual(negative_equity.status_code, 200)
        self.assertEqual(negative_equity.data['amount'], '-5.00')
        self.assertEqual(negative_equity.data['prior_amount'], '-406.00')


class DashboardAccountTests(APITestCase):
    def test_registration_accepts_gmail_addresses(self):
        registered = self.client.post('/api/account/register/', {
            'username': 'gmail-member',
            'email': 'gmail.member@gmail.com',
            'password': 'safe-password-123',
        }, format='json')

        self.assertEqual(registered.status_code, 201)
        user = get_user_model().objects.get(username='gmail-member')
        self.assertEqual(user.email, 'gmail.member@gmail.com')

    def test_registration_creates_read_only_dashboard_user_and_starts_session(self):
        registered = self.client.post('/api/account/register/', {
            'username': 'warehouse-member',
            'email': 'member@example.test',
            'password': 'safe-password-123',
        }, format='json')

        self.assertEqual(registered.status_code, 201)
        user = get_user_model().objects.get(username='warehouse-member')
        self.assertTrue(user.check_password('safe-password-123'))
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(list(user.groups.values_list('name', flat=True)), ['Dashboard viewers'])
        self.assertTrue(user.has_perm('inventory.view_product'))
        self.assertFalse(user.has_perm('inventory.add_product'))
        self.assertFalse(user.has_perm('inventory.manage_access'))
        self.assertEqual(self.client.get('/api/account/session/').status_code, 200)
        self.assertEqual(self.client.get('/api/access/session/').status_code, 200)
        self.assertEqual(self.client.get('/api/access/dashboard/').status_code, 403)
        self.assertEqual(self.client.get('/api/dashboard/summary/').status_code, 200)
        self.assertEqual(self.client.get('/api/products/').status_code, 200)
        for endpoint in (
            '/api/purchases/summary/',
            '/api/sales/summary/',
            '/api/expenses/summary/',
            '/api/expense-options/',
            '/api/expenses/balance-sheet/',
            '/api/reports/summary/',
            '/api/staff/dashboard/',
        ):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.client.get(endpoint).status_code, 200)
        self.assertEqual(self.client.post('/api/products/', {}, format='json').status_code, 403)
        self.assertEqual(self.client.post('/api/expense-options/', {
            'kind': 'type',
            'name': 'Restricted type',
        }, format='json').status_code, 403)
        self.assertEqual(self.client.delete('/api/expense-options/categories/1/').status_code, 403)
        self.assertEqual(self.client.delete('/api/expense-options/types/1/').status_code, 403)
        self.assertEqual(self.client.post('/api/balance-sheet-accounts/', {}, format='json').status_code, 403)

    def test_login_logout_and_registration_validation(self):
        duplicate = self.client.post('/api/account/register/', {
            'username': 'dashboard-user',
            'password': 'safe-password-123',
        }, format='json')
        self.assertEqual(duplicate.status_code, 201)

        repeated = self.client.post('/api/account/register/', {
            'username': 'dashboard-user',
            'password': 'safe-password-123',
        }, format='json')
        self.assertEqual(repeated.status_code, 400)

        self.client.post('/api/account/logout/', {}, format='json')
        logged_in = self.client.post('/api/account/login/', {
            'username': 'dashboard-user',
            'password': 'safe-password-123',
        }, format='json')
        self.assertEqual(logged_in.status_code, 200)
        self.assertEqual(self.client.get('/api/account/session/').status_code, 200)

    def test_staff_user_with_full_role_can_sign_in_and_access_business_dashboards(self):
        staff_admin = get_user_model().objects.create_user(
            username='staff-admin',
            password='safe-password-123',
            is_staff=True,
        )
        workspace_role = Group.objects.create(name='Authorized workspace users')
        workspace_role.permissions.add(*Permission.objects.filter(content_type__app_label='inventory'))
        staff_admin.groups.add(workspace_role)

        logged_in = self.client.post('/api/account/login/', {
            'username': staff_admin.username,
            'password': 'safe-password-123',
        }, format='json')
        self.assertEqual(logged_in.status_code, 200)
        self.assertEqual(self.client.get('/api/access/session/').status_code, 200)
        self.assertEqual(self.client.get('/api/access/dashboard/').status_code, 200)
        self.assertEqual(self.client.get('/api/dashboard/summary/').status_code, 200)

    def test_anonymous_users_cannot_read_dashboard_data(self):
        self.assertEqual(self.client.get('/api/products/').status_code, 403)
        self.assertEqual(self.client.get('/api/reports/summary/').status_code, 403)


class DashboardSummaryPerformanceTests(AdminAPITestCase):
    def test_thirty_day_summary_uses_bounded_database_queries(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/api/dashboard/summary/?range=30d')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['series']), 30)
        self.assertLessEqual(len(queries), 12, [query['sql'] for query in queries])

    def test_aggregated_summary_preserves_sales_and_legacy_movement_totals(self):
        category = Category.objects.create(name='Dashboard aggregation')
        product = Product.objects.create(
            sku='DASH-AGG-001',
            name='Dashboard aggregation product',
            category=category,
            unit_price='10.00',
            cost_price='4.00',
        )
        sale = Sale.objects.create(
            receipt_number='SALE-DASH-AGG-001',
            customer_name='Walk-in Customer',
            payment_method=Sale.PaymentMethod.CARD,
            subtotal='20.00',
            discount_amount='2.00',
            total='19.53',
        )
        SaleItem.objects.create(
            sale=sale,
            product=product,
            product_name=product.name,
            product_sku=product.sku,
            quantity=2,
            unit_price='10.00',
            unit_cost='4.00',
        )
        StockMovement.objects.create(
            product=product,
            movement_type=StockMovement.MovementType.INBOUND,
            quantity=3,
            reference='PO-LEGACY-DASH-001',
        )
        StockMovement.objects.create(
            product=product,
            movement_type=StockMovement.MovementType.OUTBOUND,
            quantity=2,
            reference='LEGACY-DASH-001',
        )
        StockMovement.objects.create(
            product=product,
            movement_type=StockMovement.MovementType.OUTBOUND,
            quantity=2,
            reference=sale.receipt_number,
        )

        response = self.client.get('/api/dashboard/summary/?range=30d')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['today_sales'], '38.00')
        self.assertEqual(response.data['period_sales'], '38.00')
        self.assertEqual(response.data['gross_profit'], '22.00')
        self.assertEqual(response.data['today_purchases'], '12.00')
        self.assertEqual(response.data['period_purchases'], '12.00')
        self.assertAlmostEqual(sum(day['sales'] for day in response.data['series']), 38.0)
        self.assertAlmostEqual(sum(day['purchases'] for day in response.data['series']), 12.0)


class AccessControlDashboardTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.admin = get_user_model().objects.create_superuser(
            username='access-admin',
            email='admin@example.test',
            password='secure-test-password',
        )

    def test_access_dashboard_rejects_anonymous_users(self):
        response = self.client.get('/api/access/dashboard/')

        self.assertIn(response.status_code, [401, 403])

    def test_dashboard_cache_is_invalidated_when_access_data_changes(self):
        self.client.force_authenticate(user=self.admin)
        first_response = self.client.get('/api/access/dashboard/')
        self.assertEqual(first_response.status_code, 200)
        self.assertNotIn('cached-workspace-user', [user['username'] for user in first_response.data['users']])

        created_user = self.client.post('/api/access/users/', {
            'username': 'cached-workspace-user',
            'password': 'temporary-password-123',
            'is_active': True,
            'is_staff': True,
        }, format='json')
        self.assertEqual(created_user.status_code, 201)

        refreshed_response = self.client.get('/api/access/dashboard/')
        self.assertIn('cached-workspace-user', [user['username'] for user in refreshed_response.data['users']])

    def test_superuser_can_create_superuser_and_status_cannot_be_changed_later(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post('/api/access/users/', {
            'username': 'new-system-admin',
            'email': 'new-admin@example.test',
            'password': 'temporary-password-123',
            'is_active': True,
            'is_staff': False,
            'is_superuser': True,
        }, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['is_superuser'])
        self.assertTrue(response.data['is_staff'])
        user = get_user_model().objects.get(username='new-system-admin')
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.check_password('temporary-password-123'))
        self.assertTrue(SecurityAuditEvent.objects.filter(
            action='user.created',
            target_id=str(user.pk),
            details__is_superuser=True,
        ).exists())

        demotion = self.client.patch(
            f'/api/access/users/{user.pk}/',
            {'is_superuser': False},
            format='json',
        )

        self.assertEqual(demotion.status_code, 400)
        user.refresh_from_db()
        self.assertTrue(user.is_superuser)

    def test_user_with_manage_access_cannot_create_superusers(self):
        permission = Permission.objects.get(
            codename='manage_access',
            content_type__app_label='inventory',
        )
        role = Group.objects.create(name='Access managers')
        role.permissions.add(permission)
        manager = get_user_model().objects.create_user(
            username='access-manager',
            password='secure-test-password',
            is_staff=True,
        )
        manager.groups.add(role)
        self.client.force_authenticate(user=manager)

        regular_user_response = self.client.post('/api/access/users/', {
            'username': 'managed-workspace-user',
            'password': 'temporary-password-123',
            'is_active': True,
            'is_staff': True,
            'is_superuser': False,
        }, format='json')
        self.assertEqual(regular_user_response.status_code, 201)
        self.assertFalse(regular_user_response.data['is_superuser'])

        response = self.client.post('/api/access/users/', {
            'username': 'unauthorized-system-admin',
            'password': 'temporary-password-123',
            'is_active': True,
            'is_staff': True,
            'is_superuser': True,
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('Only a superuser can create another superuser.', response.data['is_superuser'])
        self.assertFalse(get_user_model().objects.filter(username='unauthorized-system-admin').exists())

    def test_superuser_can_manage_roles_permissions_users_and_audit(self):
        self.client.force_authenticate(user=self.admin)
        permission = Permission.objects.get(codename='view_product', content_type__app_label='inventory')
        role = self.client.post('/api/access/groups/', {'name': 'Warehouse Operator'}, format='json')
        self.assertEqual(role.status_code, 201)

        permission_update = self.client.post('/api/access/permissions/', {
            'group_id': role.data['id'],
            'permission_ids': [permission.id],
        }, format='json')
        self.assertEqual(permission_update.status_code, 200)
        self.assertIn('product.view_product', permission_update.data['permission_labels'])

        created_user = self.client.post('/api/access/users/', {
            'username': 'warehouse-operator',
            'email': 'operator@example.test',
            'first_name': 'Morgan',
            'last_name': 'Lee',
            'password': 'temporary-password-123',
            'is_active': True,
            'is_staff': True,
            'groups': [role.data['id']],
        }, format='json')
        self.assertEqual(created_user.status_code, 201)
        user = get_user_model().objects.get(username='warehouse-operator')
        self.assertTrue(user.check_password('temporary-password-123'))
        self.assertEqual(list(user.groups.values_list('name', flat=True)), ['Warehouse Operator'])

        updated = self.client.patch(f'/api/access/users/{user.id}/', {
            'username': 'warehouse-lead',
            'password': 'new-temporary-password-456',
            'is_staff': False,
        }, format='json')
        self.assertEqual(updated.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.username, 'warehouse-lead')
        self.assertTrue(user.check_password('new-temporary-password-456'))
        self.assertFalse(user.check_password('temporary-password-123'))
        self.assertFalse(user.is_staff)
        self.assertEqual(user.groups.get().name, 'Warehouse Operator')

        disabled = self.client.patch(f"/api/access/users/{user.id}/", {'is_active': False}, format='json')
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.data['is_active'])

        dashboard = self.client.get('/api/access/dashboard/').data
        self.assertEqual(dashboard['active_users'], 1)
        self.assertEqual(dashboard['disabled_users'], 1)
        self.assertEqual(dashboard['role_count'], 1)
        self.assertTrue(any(event['action'] == 'user.created' for event in dashboard['audit_log']))
        self.assertGreaterEqual(SecurityAuditEvent.objects.count(), 3)

    def test_role_permissions_control_model_api_access(self):
        permission = Permission.objects.get(codename='view_product', content_type__app_label='inventory')
        role = Group.objects.create(name='Product viewers')
        role.permissions.add(permission)
        user = get_user_model().objects.create_user(
            username='product-viewer',
            password='secure-test-password',
            is_staff=True,
        )
        user.groups.add(role)
        self.client.force_authenticate(user=user)

        products = self.client.get('/api/products/')
        suppliers = self.client.get('/api/suppliers/')

        self.assertEqual(products.status_code, 200)
        self.assertIn(suppliers.status_code, [403, 404])

    def test_session_login_requires_csrf_and_rejects_non_superusers(self):
        client = Client(enforce_csrf_checks=True)
        csrf_response = client.get('/api/access/csrf/')
        csrf_token = csrf_response.json()['csrf_token']
        no_csrf = client.post('/api/access/login/', {'username': 'access-admin', 'password': 'secure-test-password'}, content_type='application/json')
        self.assertEqual(no_csrf.status_code, 403)

        login_response = client.post(
            '/api/access/login/',
            {'username': 'access-admin', 'password': 'secure-test-password'},
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(client.get('/api/access/session/').status_code, 200)
        self.assertTrue(SecurityAuditEvent.objects.filter(action='session.login', actor=self.admin).exists())
        rotated_csrf = login_response.json()['csrf_token']
        self.assertEqual(client.post('/api/access/logout/', '{}', content_type='application/json', HTTP_X_CSRFTOKEN=rotated_csrf).status_code, 200)
        self.assertTrue(SecurityAuditEvent.objects.filter(action='session.logout', actor=self.admin).exists())

        regular_user = get_user_model().objects.create_user(username='regular-user', password='another-password')
        denied_client = Client(enforce_csrf_checks=True)
        denied_csrf = denied_client.get('/api/access/csrf/').json()['csrf_token']
        denied = denied_client.post(
            '/api/access/login/',
            {'username': regular_user.username, 'password': 'another-password'},
            content_type='application/json',
            HTTP_X_CSRFTOKEN=denied_csrf,
        )
        self.assertEqual(denied.status_code, 400)

    def test_force_logout_deletes_target_user_sessions(self):
        user = get_user_model().objects.create_user(username='session-target', password='target-password', is_staff=True)
        user_client = Client()
        user_client.force_login(user)
        session_key = user_client.cookies['sessionid'].value
        self.assertTrue(Session.objects.filter(session_key=session_key).exists())

        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f'/api/access/users/{user.id}/force_logout/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['revoked_sessions'], 1)
        self.assertFalse(Session.objects.filter(session_key=session_key).exists())


class BootstrapSuperuserCommandTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='lord',
            password='secure-test-password',
            is_staff=True,
        )

    def bootstrap(self, username='lord', confirmation='lord'):
        call_command(
            'bootstrap_superuser',
            username=username,
            confirm_username=confirmation,
            verbosity=0,
        )

    def test_bootstraps_existing_active_user_and_records_audit_event(self):
        self.bootstrap()

        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertTrue(self.user.is_staff)
        self.assertTrue(self.user.is_superuser)
        self.assertTrue(self.user.check_password('secure-test-password'))
        self.assertTrue(SecurityAuditEvent.objects.filter(
            actor=self.user,
            action='user.superuser.bootstrapped',
            target_id=str(self.user.pk),
        ).exists())

    def test_requires_exact_username_confirmation(self):
        with self.assertRaises(CommandError):
            self.bootstrap(confirmation='someone-else')

        self.user.refresh_from_db()
        self.assertFalse(self.user.is_superuser)

    def test_refuses_to_create_an_additional_superuser(self):
        get_user_model().objects.create_superuser(
            username='existing-admin',
            password='secure-test-password',
        )

        with self.assertRaises(CommandError):
            self.bootstrap()

        self.user.refresh_from_db()
        self.assertFalse(self.user.is_superuser)

    def test_refuses_missing_or_inactive_accounts(self):
        with self.assertRaises(CommandError):
            self.bootstrap(username='missing-user', confirmation='missing-user')

        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        with self.assertRaises(CommandError):
            self.bootstrap()

        self.user.refresh_from_db()
        self.assertFalse(self.user.is_superuser)

    def test_existing_superuser_is_a_safe_no_op(self):
        self.user.is_superuser = True
        self.user.save(update_fields=['is_superuser'])

        self.bootstrap()

        self.user.refresh_from_db()
        self.assertTrue(self.user.is_superuser)
        self.assertEqual(SecurityAuditEvent.objects.count(), 0)
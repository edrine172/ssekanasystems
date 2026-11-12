import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import CustomerLedgerEntry, Expense, Notification, Product, Purchase, Sale, SupplierLedgerEntry


class AccessTokenTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_superuser(
            username='token-admin',
            password='strong-test-password',
        )
        self.client.get('/api/access/csrf/')
        self.csrf_token = self.client.cookies['csrftoken'].value

    def test_login_returns_access_token_and_httponly_refresh_cookie(self):
        response = self.client.post(
            '/api/access/login/',
            json.dumps({'username': 'token-admin', 'password': 'strong-test-password'}),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=self.csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['access_token'])
        self.assertTrue(response.cookies['stockpulse_refresh']['httponly'])
        self.assertEqual(response.cookies['stockpulse_refresh']['path'], '/api/access/token/refresh/')

    def test_access_token_authenticates_api_requests_without_a_session_cookie(self):
        login_response = self.client.post(
            '/api/access/login/',
            json.dumps({'username': 'token-admin', 'password': 'strong-test-password'}),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=self.csrf_token,
        )
        token_client = APIClient()

        response = token_client.get(
            '/api/products/',
            HTTP_AUTHORIZATION=f"Bearer {login_response.json()['access_token']}",
        )
        session_response = token_client.get(
            '/api/access/session/',
            HTTP_AUTHORIZATION=f"Bearer {login_response.json()['access_token']}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(session_response.status_code, 200)

    def test_refresh_cookie_issues_a_new_access_token(self):
        login_response = self.client.post(
            '/api/access/login/',
            json.dumps({'username': 'token-admin', 'password': 'strong-test-password'}),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=self.csrf_token,
        )

        response = self.client.post(
            '/api/access/token/refresh/',
            '{}',
            content_type='application/json',
            HTTP_X_CSRFTOKEN=login_response.json()['csrf_token'],
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['access_token'])
        self.assertEqual(
            self.client.get(
                '/api/products/',
                HTTP_AUTHORIZATION=f"Bearer {response.json()['access_token']}",
            ).status_code,
            200,
        )

    @override_settings(REST_FRAMEWORK={
        'DEFAULT_THROTTLE_RATES': {
            'anon': '60/minute',
            'user': '600/minute',
            'auth_login': '1/minute',
        },
    })
    def test_authentication_endpoints_return_429_after_rate_limit(self):
        cache.clear()
        payload = json.dumps({'username': 'unknown-user', 'password': 'wrong-password'})

        first_response = self.client.post(
            '/api/account/login/',
            payload,
            content_type='application/json',
            HTTP_X_CSRFTOKEN=self.csrf_token,
        )
        limited_response = self.client.post(
            '/api/account/login/',
            payload,
            content_type='application/json',
            HTTP_X_CSRFTOKEN=self.csrf_token,
        )

        self.assertEqual(first_response.status_code, 400)
        self.assertEqual(limited_response.status_code, 429)
        self.assertIn('Retry-After', limited_response)


class DatabaseIndexTests(TestCase):
    def test_indexes_cover_common_list_and_date_filtered_queries(self):
        expected_indexes = {
            Product: {'product_active_name_idx'},
            Sale: {'sale_customer_created_idx', 'sale_method_created_idx'},
            CustomerLedgerEntry: {'cust_ledger_created_idx', 'cust_ledger_sale_type_idx'},
            Purchase: {'purchase_supplier_date_idx', 'purchase_status_due_idx'},
            SupplierLedgerEntry: {'supp_ledger_created_idx', 'supp_ledger_purchase_type_idx'},
            Expense: {'expense_date_status_idx', 'expense_status_created_idx'},
            Notification: {'notification_active_recent_idx'},
        }

        for model, expected_names in expected_indexes.items():
            with self.subTest(model=model.__name__):
                actual_names = {index.name for index in model._meta.indexes}
                self.assertTrue(expected_names <= actual_names)

from rest_framework.permissions import BasePermission


class RoleModelPermissions(BasePermission):
    action_map = {
        'list': 'view',
        'retrieve': 'view',
        'create': 'add',
        'update': 'change',
        'partial_update': 'change',
        'destroy': 'delete',
    }
    function_permissions = {
        'dashboard-summary': {
            'GET': ('view_product', 'view_stockmovement', 'view_sale', 'view_purchase'),
        },
        'purchase-summary': {'GET': ('view_purchase', 'view_purchaseitem')},
        'sales-summary': {'GET': ('view_sale', 'view_saleitem')},
        'expenses-summary': {'GET': ('view_expense', 'view_expensebudget')},
        'expenses-balance-sheet': {
            'GET': (
                'view_balancesheetaccount', 'view_product', 'view_customer', 'view_supplier', 'view_expense',
            ),
        },
        'reports-summary': {
            'GET': (
                'view_product', 'view_stockmovement', 'view_sale', 'view_purchase',
                'view_expense', 'view_expensebudget', 'view_customer', 'view_supplier',
            ),
        },
        'system-settings': {'GET': ('view_systemsetting',), 'PATCH': ('change_systemsetting',)},
        'inventory-adjustment': {'POST': ('add_stockmovement', 'change_product')},
        'sales-checkout': {
            'POST': ('add_sale', 'add_saleitem', 'add_stockmovement', 'change_product'),
        },
        'expenses-bulk-upload': {'POST': ('add_expense',)},
        'staff-dashboard': {
            'GET': ('view_staffmember', 'view_staffattendance', 'view_payrollrun'),
        },
        'staff-attendance-list': {
            'GET': ('view_staffattendance',),
            'POST': ('add_staffattendance',),
        },
    }

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated or not user.is_active or not user.is_staff:
            return False
        if user.is_superuser:
            return True

        action = getattr(view, 'action', None)
        required_action = self.action_map.get(action)
        if required_action is None and action:
            required_action = 'view' if request.method in ('GET', 'HEAD', 'OPTIONS') else 'change'

        queryset = getattr(view, 'queryset', None)
        if queryset is None and hasattr(view, 'get_queryset'):
            queryset = view.get_queryset()
        model = getattr(queryset, 'model', None)
        if model is not None:
            required_action = required_action or (
                'view' if request.method in ('GET', 'HEAD', 'OPTIONS')
                else 'add' if request.method == 'POST'
                else 'delete' if request.method == 'DELETE'
                else 'change'
            )
            return user.has_perm(f'{model._meta.app_label}.{required_action}_{model._meta.model_name}')

        url_name = getattr(request.resolver_match, 'url_name', None)
        permissions = self.function_permissions.get(url_name, {}).get(request.method)
        if permissions is None:
            return False
        return user.has_perms([f'inventory.{codename}' for codename in permissions])

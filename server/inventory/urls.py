from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .backups import download_database_backup, restore_database_backup
from .access_control import AccessDashboardViewSet, AccessGroupViewSet, AccessPermissionViewSet, AccessUserViewSet, access_csrf, access_login, access_logout, access_session, account_login, account_logout, account_register, account_session
from .views import BalanceSheetAccountViewSet, BottleCustomerPOViewSet, BottleProductViewSet, CategoryViewSet, ClientMaterialPOViewSet, ClientMaterialViewSet, CustomerViewSet, ExpenseBudgetViewSet, ExpenseViewSet, NotificationViewSet, PayrollRunViewSet, ProductViewSet, PurchaseViewSet, SaleViewSet, StaffAttendanceViewSet, StaffMemberViewSet, StaffTaskAssignmentViewSet, StaffTaskEntryViewSet, StaffTaskViewSet, StockMovementViewSet, SupplierViewSet, balance_sheet_summary, checkout, dashboard_summary, delete_expense_category, delete_expense_type, exchange_rates, expense_options, expenses_bulk_upload, expenses_summary, inventory_adjustment, purchase_summary, reports_summary, sales_summary, staff_dashboard, system_settings

router = DefaultRouter()
router.register('products', ProductViewSet)
router.register('notifications', NotificationViewSet, basename='notification')
router.register('categories', CategoryViewSet)
router.register('customers', CustomerViewSet)
router.register('suppliers', SupplierViewSet)
router.register('expenses', ExpenseViewSet)
router.register('expense-budgets', ExpenseBudgetViewSet)
router.register('balance-sheet-accounts', BalanceSheetAccountViewSet)
router.register('staff/workers', StaffMemberViewSet, basename='staff-worker')
router.register('staff/attendance', StaffAttendanceViewSet, basename='staff-attendance')
router.register('staff/tasks', StaffTaskViewSet, basename='staff-task')
router.register('staff/task-assignments', StaffTaskAssignmentViewSet, basename='staff-task-assignment')
router.register('staff/task-entries', StaffTaskEntryViewSet, basename='staff-task-entry')
router.register('staff/payroll-runs', PayrollRunViewSet, basename='staff-payroll-run')
router.register('access/users', AccessUserViewSet, basename='access-user')
router.register('access/groups', AccessGroupViewSet, basename='access-group')
router.register('access/permissions', AccessPermissionViewSet, basename='access-permission')
router.register('access/dashboard', AccessDashboardViewSet, basename='access-dashboard')
router.register('purchases', PurchaseViewSet)
router.register('po-client/bottle-products', BottleProductViewSet, basename='po-client-bottle-product')
router.register('po-client/bottle-orders', BottleCustomerPOViewSet, basename='po-client-bottle-order')
router.register('po-client/materials', ClientMaterialViewSet, basename='po-client-material')
router.register('po-client/material-orders', ClientMaterialPOViewSet, basename='po-client-material-order')
router.register('sales', SaleViewSet)
router.register('movements', StockMovementViewSet)

urlpatterns = [
    path('system/backup/', download_database_backup, name='system-backup'),
    path('system/backup/restore/', restore_database_backup, name='system-backup-restore'),
    path('access/csrf/', access_csrf, name='access-csrf'),
    path('access/login/', access_login, name='access-login'),
    path('access/session/', access_session, name='access-session'),
    path('access/logout/', access_logout, name='access-logout'),
    path('account/register/', account_register, name='account-register'),
    path('account/login/', account_login, name='account-login'),
    path('account/session/', account_session, name='account-session'),
    path('account/logout/', account_logout, name='account-logout'),
    path('inventory/adjustments/', inventory_adjustment, name='inventory-adjustment'),
    path('purchases/summary/', purchase_summary, name='purchase-summary'),
    path('sales/checkout/', checkout, name='sales-checkout'),
    path('sales/summary/', sales_summary, name='sales-summary'),
    path('reports/summary/', reports_summary, name='reports-summary'),
    path('expenses/summary/', expenses_summary, name='expenses-summary'),
    path('expenses/balance-sheet/', balance_sheet_summary, name='expenses-balance-sheet'),
    path('expenses/bulk-upload/', expenses_bulk_upload, name='expenses-bulk-upload'),
    path('expense-options/', expense_options, name='expense-options'),
    path('expense-options/categories/<int:category_id>/', delete_expense_category, name='expense-category-option'),
    path('expense-options/types/<int:type_id>/', delete_expense_type, name='expense-type-option'),
    path('settings/', system_settings, name='system-settings'),
    path('exchange-rates/', exchange_rates, name='exchange-rates'),
    path('staff/dashboard/', staff_dashboard, name='staff-dashboard'),
    path('', include(router.urls)),
    path('dashboard/summary/', dashboard_summary, name='dashboard-summary'),
]

from django.db import migrations, models


CATEGORIES = [
    ('cash_and_cash_equivalents', 'Cash and cash equivalents'),
    ('current_marketable_securities', 'Marketable securities'),
    ('accounts_receivable_net', 'Accounts receivable, net'),
    ('inventories', 'Inventories'),
    ('vendor_non_trade_receivables', 'Vendor non-trade receivables'),
    ('other_current_assets', 'Other current assets'),
    ('noncurrent_marketable_securities', 'Marketable securities'),
    ('property_plant_equipment_net', 'Property, plant and equipment, net'),
    ('other_noncurrent_assets', 'Other non-current assets'),
    ('accounts_payable', 'Accounts payable'),
    ('other_current_liabilities', 'Other current liabilities'),
    ('deferred_revenue', 'Deferred revenue'),
    ('commercial_paper', 'Commercial paper'),
    ('current_term_debt', 'Term debt'),
    ('noncurrent_term_debt', 'Term debt'),
    ('other_noncurrent_liabilities', 'Other non-current liabilities'),
    ('common_stock_and_additional_paid_in_capital', 'Common stock and additional paid-in capital'),
    ('retained_earnings', 'Retained earnings'),
    ('accumulated_other_comprehensive_income_loss', 'Accumulated other comprehensive income / (loss)'),
]


def migrate_balance_sheet_accounts(apps, schema_editor):
    Account = apps.get_model('inventory', 'BalanceSheetAccount')
    mapping = {
        ('asset', 'cash'): 'cash_and_cash_equivalents',
        ('asset', 'cash and cash equivalents'): 'cash_and_cash_equivalents',
        ('asset', 'marketable securities'): 'current_marketable_securities',
        ('asset', 'accounts receivable'): 'accounts_receivable_net',
        ('asset', 'accounts receivable, net'): 'accounts_receivable_net',
        ('asset', 'inventory'): 'inventories',
        ('asset', 'inventories'): 'inventories',
        ('asset', 'vendor non-trade receivables'): 'vendor_non_trade_receivables',
        ('asset', 'property, plant and equipment, net'): 'property_plant_equipment_net',
        ('liability', 'accounts payable'): 'accounts_payable',
        ('liability', 'approved unpaid expenses'): 'other_current_liabilities',
        ('liability', 'other current liabilities'): 'other_current_liabilities',
        ('liability', 'deferred revenue'): 'deferred_revenue',
        ('liability', 'commercial paper'): 'commercial_paper',
        ('liability', 'term debt'): 'noncurrent_term_debt',
        ('equity', "owner's capital"): 'common_stock_and_additional_paid_in_capital',
        ('equity', 'common stock and additional paid-in capital'): 'common_stock_and_additional_paid_in_capital',
        ('equity', 'retained earnings'): 'retained_earnings',
        ('equity', 'accumulated other comprehensive income / (loss)'): 'accumulated_other_comprehensive_income_loss',
    }

    assigned = {}
    for account in Account.objects.order_by('pk'):
        account_type = account.account_type
        key = (account_type, account.name.strip().casefold())
        category = mapping.get(key)
        if category is None:
            category = {
                'asset': 'other_current_assets',
                'liability': 'other_current_liabilities',
                'equity': 'retained_earnings',
            }[account_type]
        if category in assigned:
            previous = Account.objects.get(pk=assigned[category])
            previous.amount += account.amount
            previous.save(update_fields=['amount'])
            account.delete()
            continue
        account.category = category
        account.save(update_fields=['category'])
        assigned[category] = account.pk

    for category, _ in CATEGORIES:
        Account.objects.get_or_create(
            category=category,
            defaults={'amount': None, 'prior_amount': None},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0029_balance_sheet_account'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='balancesheetaccount',
            name='unique_balance_sheet_account',
        ),
        migrations.AddField(
            model_name='balancesheetaccount',
            name='category',
            field=models.CharField(blank=True, choices=CATEGORIES, max_length=64, null=True),
        ),
        migrations.AlterField(
            model_name='balancesheetaccount',
            name='amount',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='balancesheetaccount',
            name='prior_amount',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.RunPython(migrate_balance_sheet_accounts, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='balancesheetaccount',
            name='category',
            field=models.CharField(choices=CATEGORIES, max_length=64, unique=True),
        ),
        migrations.RemoveField(
            model_name='balancesheetaccount',
            name='account_type',
        ),
        migrations.RemoveField(
            model_name='balancesheetaccount',
            name='name',
        ),
        migrations.AlterModelOptions(
            name='balancesheetaccount',
            options={'ordering': ['category']},
        ),
    ]

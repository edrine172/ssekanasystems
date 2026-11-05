from django.db import migrations, models
from django.utils.text import slugify


DEFAULT_CATEGORIES = [
    'Logistics & Freight',
    'Facilities & Maintenance',
    'Software & Cloud',
    'Packaging & Supplies',
    'Utilities & Cloud',
    'Office & Admin',
    'Other',
]

DEFAULT_TYPES = [
    ('operational', 'Operational'),
    ('freight', 'Freight'),
    ('capital', 'Capital expenditure'),
]


def create_expense_options(apps, schema_editor):
    Expense = apps.get_model('inventory', 'Expense')
    ExpenseBudget = apps.get_model('inventory', 'ExpenseBudget')
    ExpenseCategory = apps.get_model('inventory', 'ExpenseCategory')
    ExpenseTypeOption = apps.get_model('inventory', 'ExpenseTypeOption')
    database = schema_editor.connection.alias

    for name in DEFAULT_CATEGORIES:
        ExpenseCategory.objects.using(database).get_or_create(name=name)
    for value, label in DEFAULT_TYPES:
        ExpenseTypeOption.objects.using(database).get_or_create(value=value, defaults={'label': label})

    existing_categories = Expense.objects.using(database).values_list('category', flat=True).distinct()
    for name in existing_categories:
        if name:
            ExpenseCategory.objects.using(database).get_or_create(name=name[:80])
    budget_categories = ExpenseBudget.objects.using(database).values_list('category', flat=True)
    for name in budget_categories:
        if name:
            ExpenseCategory.objects.using(database).get_or_create(name=name[:80])

    existing_types = Expense.objects.using(database).values_list('expense_type', flat=True).distinct()
    for value in existing_types:
        if not value or value in {known_value for known_value, _ in DEFAULT_TYPES}:
            continue
        slug = slugify(value)[:80] or 'custom-expense'
        base_slug = slug
        suffix = 2
        while ExpenseTypeOption.objects.using(database).exclude(label=value[:80]).filter(value=slug).exists():
            slug = f'{base_slug[:70]}-{suffix}'
            suffix += 1
        ExpenseTypeOption.objects.using(database).get_or_create(value=slug, defaults={'label': value[:80]})
        Expense.objects.using(database).filter(expense_type=value).update(expense_type=slug)


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0030_balance_sheet_categories'),
    ]

    operations = [
        migrations.CreateModel(
            name='ExpenseCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80, unique=True)),
            ],
            options={'ordering': ['name']},
        ),
        migrations.CreateModel(
            name='ExpenseTypeOption',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('value', models.SlugField(max_length=80, unique=True)),
                ('label', models.CharField(max_length=80, unique=True)),
            ],
            options={'ordering': ['label']},
        ),
        migrations.AlterField(
            model_name='expense',
            name='expense_type',
            field=models.CharField(default='operational', max_length=80),
        ),
        migrations.RunPython(create_expense_options, migrations.RunPython.noop),
    ]

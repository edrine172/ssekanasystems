from decimal import Decimal
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers
from .models import BalanceSheetAccount, Expense, ExpenseBudget, ExpenseCategory, ExpenseTypeOption


class ExpenseSerializer(serializers.ModelSerializer):
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    amount_before_tax = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'))
    tax_amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'), required=False, default=Decimal('0'))

    def validate(self, attrs):
        category = attrs.get('category', self.instance.category if self.instance else None)
        expense_type = attrs.get('expense_type', self.instance.expense_type if self.instance else Expense.ExpenseType.OPERATIONAL)
        errors = {}
        if category and not ExpenseCategory.objects.filter(name=category).exists():
            errors['category'] = 'Choose an existing expense category.'
        if expense_type and not ExpenseTypeOption.objects.filter(value=expense_type).exists():
            errors['expense_type'] = 'Choose an existing expense type.'
        if errors:
            raise serializers.ValidationError(errors)
        amount_before_tax = attrs.get('amount_before_tax', getattr(self.instance, 'amount_before_tax', Decimal('0')))
        tax_amount = attrs.get('tax_amount', getattr(self.instance, 'tax_amount', Decimal('0')))
        if amount_before_tax + tax_amount <= 0:
            raise serializers.ValidationError({'amount_before_tax': 'Expense total must be greater than zero.'})
        receipt_received = attrs.get('receipt_received', getattr(self.instance, 'receipt_received', False))
        receipt_verified = attrs.get('receipt_verified', getattr(self.instance, 'receipt_verified', False))
        if receipt_verified and not receipt_received:
            raise serializers.ValidationError({'receipt_verified': 'A receipt must be received before it can be verified.'})
        return attrs

    def create(self, validated_data):
        from uuid import uuid4
        validated_data['expense_number'] = f"EXP-{timezone.now().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"
        validated_data['total_amount'] = validated_data['amount_before_tax'] + validated_data.get('tax_amount', Decimal('0'))
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if 'amount_before_tax' in validated_data or 'tax_amount' in validated_data:
            before_tax = validated_data.get('amount_before_tax', instance.amount_before_tax)
            tax = validated_data.get('tax_amount', instance.tax_amount)
            validated_data['total_amount'] = before_tax + tax
        return super().update(instance, validated_data)

    class Meta:
        model = Expense
        fields = [
            'id', 'expense_number', 'merchant', 'description', 'category', 'cost_center', 'expense_type',
            'amount_before_tax', 'tax_amount', 'total_amount', 'payment_method', 'payment_method_display',
            'status', 'status_display', 'reference', 'expense_date', 'receipt_received', 'receipt_verified',
            'entered_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'expense_number', 'total_amount', 'created_at', 'updated_at']


class ExpenseBudgetSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseBudget
        fields = ['id', 'category', 'monthly_limit', 'cost_center', 'manager', 'updated_at']
        read_only_fields = ['id', 'updated_at']


class ExpenseCategorySerializer(serializers.ModelSerializer):
    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Enter an expense category name.')
        if ExpenseCategory.objects.filter(name__iexact=value).exists():
            raise serializers.ValidationError('This expense category already exists.')
        return value

    class Meta:
        model = ExpenseCategory
        fields = ['id', 'name']
        read_only_fields = ['id']


class ExpenseTypeOptionSerializer(serializers.ModelSerializer):
    value = serializers.SlugField(read_only=True)
    label = serializers.CharField(max_length=80)

    def validate_label(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Enter an expense type name.')
        if ExpenseTypeOption.objects.filter(label__iexact=value).exists():
            raise serializers.ValidationError('This expense type already exists.')
        if not slugify(value):
            raise serializers.ValidationError('Enter a name containing letters or numbers.')
        return value

    def create(self, validated_data):
        base_value = slugify(validated_data['label'])[:80]
        value = base_value
        suffix = 2
        while ExpenseTypeOption.objects.filter(value=value).exists():
            suffix_text = f'-{suffix}'
            value = f'{base_value[:80 - len(suffix_text)]}{suffix_text}'
            suffix += 1
        return ExpenseTypeOption.objects.create(value=value, **validated_data)

    class Meta:
        model = ExpenseTypeOption
        fields = ['id', 'value', 'label']
        read_only_fields = ['id', 'value']


class BalanceSheetAccountSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    prior_amount = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)

    class Meta:
        model = BalanceSheetAccount
        fields = ['id', 'category', 'amount', 'prior_amount', 'updated_at']
        read_only_fields = ['id', 'category', 'updated_at']

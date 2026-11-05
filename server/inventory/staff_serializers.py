from decimal import Decimal
from rest_framework import serializers
from .models import PayrollLine, PayrollRun, StaffAttendance, StaffMember, StaffTask, StaffTaskAssignment, StaffTaskEntry


class StaffMemberSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    pay_basis_display = serializers.CharField(source='get_pay_basis_display', read_only=True)
    period_days_worked = serializers.SerializerMethodField()
    period_gross = serializers.SerializerMethodField()
    period_task_pay = serializers.SerializerMethodField()

    def get_period_days_worked(self, worker):
        return self.context.get('attendance_totals', {}).get(worker.id, {}).get('days_worked', 0)

    def get_period_gross(self, worker):
        totals = self.context.get('attendance_totals', {}).get(worker.id, {})
        return totals.get('gross', Decimal('0.00'))

    def get_period_task_pay(self, worker):
        return self.context.get('task_pay_totals', {}).get(worker.id, Decimal('0.00'))

    def validate(self, attrs):
        pay_basis = attrs.get('pay_basis', getattr(self.instance, 'pay_basis', StaffMember.PayBasis.MONTHLY))
        pay_rate = attrs.get('pay_rate', getattr(self.instance, 'pay_rate', Decimal('0')))
        hours = attrs.get('hours_per_period', getattr(self.instance, 'hours_per_period', Decimal('160')))
        withholding_percent = attrs.get('withholding_percent', getattr(self.instance, 'withholding_percent', Decimal('0')))
        benefits = attrs.get('benefit_deduction', getattr(self.instance, 'benefit_deduction', Decimal('0')))
        gross = pay_rate if pay_basis in (StaffMember.PayBasis.MONTHLY, StaffMember.PayBasis.DAILY) else pay_rate * hours
        if pay_rate <= 0:
            raise serializers.ValidationError({'pay_rate': 'Pay rate must be greater than zero.'})
        if pay_basis == StaffMember.PayBasis.HOURLY and hours <= 0:
            raise serializers.ValidationError({'hours_per_period': 'Hours per pay period must be greater than zero.'})
        if withholding_percent < 0 or withholding_percent > 100:
            raise serializers.ValidationError({'withholding_percent': 'Withholding must be between 0 and 100 percent.'})
        if benefits < 0 or (pay_basis != StaffMember.PayBasis.DAILY and gross * withholding_percent / Decimal('100') + benefits > gross):
            raise serializers.ValidationError({'benefit_deduction': 'Configured deductions cannot exceed gross pay.'})
        return attrs

    class Meta:
        model = StaffMember
        fields = [
            'id', 'employee_number', 'full_name', 'email', 'phone', 'job_title', 'department',
            'pay_basis', 'pay_basis_display', 'pay_rate', 'hours_per_period', 'withholding_percent',
            'benefit_deduction', 'status', 'status_display', 'hire_date', 'period_days_worked', 'period_gross',
            'period_task_pay', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'employee_number', 'created_at', 'updated_at']


class PayrollLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollLine
        fields = [
            'id', 'worker', 'employee_number', 'worker_name', 'job_title', 'department',
            'pay_basis', 'hours', 'days_worked', 'task_pay', 'gross_pay', 'withholding', 'benefits', 'net_pay',
        ]


class StaffTaskSerializer(serializers.ModelSerializer):
    pay_basis_display = serializers.CharField(source='get_pay_basis_display', read_only=True)
    target_tiers = serializers.ListField(child=serializers.DictField(), required=False)

    def validate(self, attrs):
        pay_basis = attrs.get('pay_basis', self.instance.pay_basis if self.instance else None)
        target_tiers = attrs.get(
            'target_tiers',
            self.instance.target_tiers if self.instance else [],
        )
        if pay_basis == StaffTask.PayBasis.TARGET:
            if not target_tiers:
                raise serializers.ValidationError({'target_tiers': 'Add at least one target and payout for target-based tasks.'})
            validated_tiers = []
            for tier in target_tiers:
                try:
                    if set(tier) != {'target_quantity', 'amount'}:
                        raise ValueError
                    raw_target = tier['target_quantity']
                    if isinstance(raw_target, bool) or str(raw_target).strip() != str(int(raw_target)):
                        raise ValueError
                    target = int(raw_target)
                    amount = Decimal(str(tier['amount']))
                except (KeyError, TypeError, ValueError, ArithmeticError):
                    raise serializers.ValidationError({'target_tiers': 'Each tier needs a whole-number target and a valid payout amount.'})
                if target <= 0 or amount <= 0 or not amount.is_finite():
                    raise serializers.ValidationError({'target_tiers': 'Tier targets and payout amounts must be greater than zero.'})
                validated_tiers.append({'target_quantity': target, 'amount': str(amount)})
            targets = [tier['target_quantity'] for tier in validated_tiers]
            if len(targets) != len(set(targets)):
                raise serializers.ValidationError({'target_tiers': 'Each target quantity must be unique.'})
            attrs['target_tiers'] = sorted(validated_tiers, key=lambda tier: tier['target_quantity'])
            attrs['pay_rate'] = max(Decimal(tier['amount']) for tier in attrs['target_tiers'])
        elif target_tiers:
            attrs['target_tiers'] = []
        if (
            self.instance
            and attrs.get('pay_basis', self.instance.pay_basis) != self.instance.pay_basis
            and self.instance.work_entries.exists()
        ):
            raise serializers.ValidationError({'pay_basis': 'A task pay basis cannot change after work has been recorded.'})
        return attrs

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Enter a task name.')
        return value

    def validate_pay_rate(self, value):
        if value <= 0:
            raise serializers.ValidationError('Task pay rate must be greater than zero.')
        return value

    class Meta:
        model = StaffTask
        fields = ['id', 'name', 'pay_basis', 'pay_basis_display', 'pay_rate', 'target_tiers', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class StaffTaskEntryInputSerializer(serializers.Serializer):
    worker = serializers.PrimaryKeyRelatedField(queryset=StaffMember.objects.all())
    task = serializers.PrimaryKeyRelatedField(queryset=StaffTask.objects.all())
    hours = serializers.DecimalField(max_digits=7, decimal_places=2, min_value=Decimal('0'), required=False, default=Decimal('0'))
    units_worked = serializers.IntegerField(min_value=0, required=False, default=0)

    def validate(self, attrs):
        task = attrs['task']
        if task.pay_basis == StaffTask.PayBasis.HOURLY and attrs['hours'] <= 0:
            raise serializers.ValidationError({'hours': 'Enter hours worked for an hourly task.'})
        if task.pay_basis != StaffTask.PayBasis.HOURLY:
            attrs['hours'] = Decimal('0')
        if task.pay_basis != StaffTask.PayBasis.TARGET:
            attrs['units_worked'] = 0
        return attrs


class StaffTaskEntryRemovalInputSerializer(serializers.Serializer):
    date = serializers.DateField(input_formats=['%Y-%m-%d'])
    worker = serializers.PrimaryKeyRelatedField(queryset=StaffMember.objects.all())
    task = serializers.PrimaryKeyRelatedField(queryset=StaffTask.objects.all())


class StaffTaskEntrySerializer(serializers.ModelSerializer):
    worker_name = serializers.CharField(source='worker.full_name', read_only=True)
    employee_number = serializers.CharField(source='worker.employee_number', read_only=True)
    pay_basis_display = serializers.CharField(source='get_pay_basis_display', read_only=True)

    class Meta:
        model = StaffTaskEntry
        fields = [
            'id', 'worker', 'worker_name', 'employee_number', 'task', 'task_name', 'date', 'assignment_type',
            'pay_basis', 'pay_basis_display', 'pay_rate', 'hours', 'target_tiers', 'units_worked', 'created_at',
        ]
        read_only_fields = fields


class StaffTaskAssignmentSerializer(serializers.ModelSerializer):
    worker_name = serializers.CharField(source='worker.full_name', read_only=True)
    task_name = serializers.CharField(source='task.name', read_only=True)
    pay_basis = serializers.CharField(source='task.pay_basis', read_only=True)
    pay_basis_display = serializers.CharField(source='task.get_pay_basis_display', read_only=True)
    pay_rate = serializers.DecimalField(source='task.pay_rate', max_digits=12, decimal_places=2, read_only=True)
    target_tiers = serializers.ListField(source='task.target_tiers', child=serializers.DictField(), read_only=True)

    def validate(self, attrs):
        worker = attrs.get('worker', self.instance.worker if self.instance else None)
        task = attrs.get('task', self.instance.task if self.instance else None)
        assigned_from = attrs.get('assigned_from', self.instance.assigned_from if self.instance else None)
        is_active = attrs.get('is_active', self.instance.is_active if self.instance else True)
        if worker and worker.status != StaffMember.Status.ACTIVE:
            raise serializers.ValidationError({'worker': 'Only active workers can receive permanent task assignments.'})
        if worker and assigned_from and assigned_from < worker.hire_date:
            raise serializers.ValidationError({'assigned_from': 'The assignment cannot start before the worker’s hire date.'})
        if task and not task.is_active:
            raise serializers.ValidationError({'task': 'Only active tasks can be permanently assigned.'})
        if worker and task and is_active:
            active_assignments = StaffTaskAssignment.objects.filter(worker=worker, task=task, is_active=True)
            if self.instance:
                active_assignments = active_assignments.exclude(pk=self.instance.pk)
            if active_assignments.exists():
                raise serializers.ValidationError({'task': 'This worker is already permanently assigned to this task.'})
        return attrs

    class Meta:
        model = StaffTaskAssignment
        fields = [
            'id', 'worker', 'worker_name', 'task', 'task_name', 'pay_basis', 'pay_basis_display',
            'pay_rate', 'target_tiers', 'assigned_from', 'is_active', 'created_at',
        ]
        read_only_fields = ['id', 'worker_name', 'task_name', 'pay_basis', 'pay_basis_display', 'pay_rate', 'target_tiers', 'created_at']


class StaffAttendanceInputSerializer(serializers.Serializer):
    worker = serializers.PrimaryKeyRelatedField(queryset=StaffMember.objects.all())
    attended = serializers.BooleanField()
    output_quantity = serializers.IntegerField(min_value=0, required=False, default=0)
    daily_wage_override = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal('0.00'), required=False, allow_null=True,
    )

    def validate(self, attrs):
        attrs.setdefault('daily_wage_override', None)
        if not attrs['attended'] or attrs['worker'].pay_basis != StaffMember.PayBasis.DAILY:
            attrs['output_quantity'] = 0
            attrs['daily_wage_override'] = None
        elif attrs['output_quantity'] >= 8 and attrs.get('daily_wage_override') is not None:
            raise serializers.ValidationError({'daily_wage_override': 'A supervisor wage override is only allowed below 8 units.'})
        return attrs


class StaffAttendanceSerializer(serializers.ModelSerializer):
    worker_name = serializers.CharField(source='worker.full_name', read_only=True)
    employee_number = serializers.CharField(source='worker.employee_number', read_only=True)

    class Meta:
        model = StaffAttendance
        fields = ['id', 'worker', 'worker_name', 'employee_number', 'date', 'attended', 'output_quantity', 'daily_wage_override', 'daily_wage', 'created_at', 'updated_at']
        read_only_fields = ['id', 'worker_name', 'employee_number', 'created_at', 'updated_at']


class PayrollRunSerializer(serializers.ModelSerializer):
    lines = PayrollLineSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = PayrollRun
        fields = [
            'id', 'period', 'status', 'status_display', 'worker_count', 'gross_total',
            'withholding_total', 'benefits_total', 'net_total', 'created_at', 'paid_at', 'lines',
        ]
        read_only_fields = fields

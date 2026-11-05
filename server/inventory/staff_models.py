from django.db import models
from django.utils import timezone
from uuid import uuid4


def generate_employee_number():
    return f'EMP-{uuid4().hex[:10].upper()}'


class StaffMember(models.Model):
    class PayBasis(models.TextChoices):
        MONTHLY = 'monthly', 'Monthly salary'
        HOURLY = 'hourly', 'Hourly wage'
        DAILY = 'daily', 'Daily wage'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        LEAVE = 'leave', 'On leave'
        INACTIVE = 'inactive', 'Inactive'

    employee_number = models.CharField(max_length=24, unique=True, default=generate_employee_number)
    full_name = models.CharField(max_length=160)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    job_title = models.CharField(max_length=120)
    department = models.CharField(max_length=100)
    pay_basis = models.CharField(max_length=12, choices=PayBasis.choices, default=PayBasis.MONTHLY)
    pay_rate = models.DecimalField(max_digits=12, decimal_places=2)
    hours_per_period = models.DecimalField(max_digits=6, decimal_places=2, default=160)
    withholding_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    benefit_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    hire_date = models.DateField(default=timezone.localdate)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['full_name', 'employee_number']

    def __str__(self):
        return f'{self.employee_number} · {self.full_name}'


class StaffAttendance(models.Model):
    worker = models.ForeignKey(StaffMember, on_delete=models.PROTECT, related_name='attendance_records')
    date = models.DateField()
    attended = models.BooleanField(default=False)
    output_quantity = models.PositiveIntegerField(default=0)
    daily_wage_override = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    daily_wage = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    recorded_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='staff_attendance_records')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date', 'worker__full_name']
        constraints = [models.UniqueConstraint(fields=['worker', 'date'], name='unique_staff_attendance_per_day')]

    def __str__(self):
        return f'{self.worker.employee_number} · {self.date}'


class StaffTask(models.Model):
    class PayBasis(models.TextChoices):
        DAILY = 'daily', 'Daily'
        HOURLY = 'hourly', 'Hourly'
        MONTHLY = 'monthly', 'Monthly'
        TARGET = 'target', 'Target-based'

    name = models.CharField(max_length=120, unique=True)
    pay_basis = models.CharField(max_length=12, choices=PayBasis.choices)
    pay_rate = models.DecimalField(max_digits=12, decimal_places=2)
    target_tiers = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class StaffTaskAssignment(models.Model):
    worker = models.ForeignKey(StaffMember, on_delete=models.PROTECT, related_name='permanent_task_assignments')
    task = models.ForeignKey(StaffTask, on_delete=models.PROTECT, related_name='permanent_assignments')
    assigned_from = models.DateField(default=timezone.localdate)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['worker__full_name', 'task__name']
        constraints = [
            models.UniqueConstraint(
                fields=['worker', 'task'],
                condition=models.Q(is_active=True),
                name='unique_active_staff_task_assignment',
            ),
        ]

    def __str__(self):
        return f'{self.worker.employee_number} · {self.task.name}'


class StaffTaskEntry(models.Model):
    class AssignmentType(models.TextChoices):
        DAILY = 'daily', 'Daily assignment'
        PERMANENT = 'permanent', 'Permanent assignment'

    worker = models.ForeignKey(StaffMember, on_delete=models.PROTECT, related_name='task_entries')
    task = models.ForeignKey(StaffTask, on_delete=models.PROTECT, related_name='work_entries')
    date = models.DateField()
    assignment_type = models.CharField(max_length=12, choices=AssignmentType.choices, default=AssignmentType.DAILY)
    task_name = models.CharField(max_length=120)
    pay_basis = models.CharField(max_length=12, choices=StaffTask.PayBasis.choices)
    pay_rate = models.DecimalField(max_digits=12, decimal_places=2)
    hours = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    target_tiers = models.JSONField(default=list, blank=True)
    units_worked = models.PositiveIntegerField(default=0)
    recorded_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='staff_task_entries')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date', 'worker__full_name', 'task_name']
        constraints = [
            models.UniqueConstraint(fields=['worker', 'task', 'date'], name='unique_staff_task_per_worker_day'),
        ]
        indexes = [
            models.Index(fields=['date', 'worker'], name='staff_task_date_worker_idx'),
        ]

    def __str__(self):
        return f'{self.worker.employee_number} · {self.task_name} · {self.date}'


class PayrollRun(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = 'scheduled', 'Scheduled'
        PAID = 'paid', 'Paid'

    period = models.CharField(max_length=7)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED)
    worker_count = models.PositiveIntegerField(default=0)
    gross_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    withholding_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    benefits_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='inventory_payroll_runs')
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-period', '-created_at']
        constraints = [models.UniqueConstraint(fields=['period'], name='unique_payroll_run_per_period')]

    def __str__(self):
        return f'Payroll {self.period}'


class PayrollLine(models.Model):
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name='lines')
    worker = models.ForeignKey(StaffMember, on_delete=models.PROTECT, related_name='payroll_lines')
    employee_number = models.CharField(max_length=24)
    worker_name = models.CharField(max_length=160)
    job_title = models.CharField(max_length=120)
    department = models.CharField(max_length=100)
    pay_basis = models.CharField(max_length=12, choices=StaffMember.PayBasis.choices)
    hours = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    days_worked = models.PositiveIntegerField(default=0)
    task_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gross_pay = models.DecimalField(max_digits=12, decimal_places=2)
    withholding = models.DecimalField(max_digits=12, decimal_places=2)
    benefits = models.DecimalField(max_digits=12, decimal_places=2)
    net_pay = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ['worker_name', 'employee_number']
        constraints = [models.UniqueConstraint(fields=['run', 'worker'], name='unique_worker_per_payroll_run')]

    def __str__(self):
        return f'{self.employee_number} · {self.run.period}'

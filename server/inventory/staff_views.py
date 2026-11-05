from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework import viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from .models import PayrollLine, PayrollRun, SecurityAuditEvent, StaffAttendance, StaffMember, StaffTask, StaffTaskAssignment, StaffTaskEntry
from .serializers import PayrollRunSerializer, StaffAttendanceInputSerializer, StaffAttendanceSerializer, StaffMemberSerializer, StaffTaskAssignmentSerializer, StaffTaskEntryInputSerializer, StaffTaskEntryRemovalInputSerializer, StaffTaskEntrySerializer, StaffTaskSerializer
from .permissions import RoleModelPermissions


DAILY_WAGE_TIERS = (
    (15, Decimal('7000.00')),
    (12, Decimal('6000.00')),
    (10, Decimal('5000.00')),
    (8, Decimal('4000.00')),
)


SUNDAY_WAGE_TIERS = (
    (15, Decimal('7000.00')),
    (12, Decimal('6000.00')),
    (10, Decimal('5000.00')),
    (8, Decimal('4000.00')),
)


def daily_attendance_wage(work_date, attended, output_quantity, wage_override=None):
    if not attended:
        return Decimal('0.00')
    wage_tiers = SUNDAY_WAGE_TIERS if work_date.weekday() == 6 else DAILY_WAGE_TIERS
    return next(
        (wage for units, wage in wage_tiers if output_quantity >= units),
        wage_override if wage_override is not None else Decimal('0.00'),
    )


def refresh_daily_attendance_wage(worker, work_date):
    attendance = StaffAttendance.objects.filter(worker=worker, date=work_date).first()
    if not attendance:
        return
    if (
        attendance.attended
        and worker.pay_basis == StaffMember.PayBasis.DAILY
        and not StaffTaskEntry.objects.filter(worker=worker, date=work_date).exists()
    ):
        wage = daily_attendance_wage(work_date, True, attendance.output_quantity, attendance.daily_wage_override)
    else:
        wage = Decimal('0.00')
    if attendance.daily_wage != wage:
        attendance.daily_wage = wage
        attendance.save(update_fields=['daily_wage'])


def task_pay_totals(entries):
    totals = {}
    monthly_rates = {}
    for entry in entries:
        if entry.pay_basis == StaffTask.PayBasis.DAILY:
            totals[entry.worker_id] = totals.get(entry.worker_id, Decimal('0')) + entry.pay_rate
        elif entry.pay_basis == StaffTask.PayBasis.HOURLY:
            totals[entry.worker_id] = totals.get(entry.worker_id, Decimal('0')) + entry.pay_rate * entry.hours
        elif entry.pay_basis == StaffTask.PayBasis.TARGET:
            reached_tiers = [
                tier for tier in entry.target_tiers
                if entry.units_worked >= tier['target_quantity']
            ]
            payout = max(
                (Decimal(str(tier['amount'])) for tier in reached_tiers),
                default=Decimal('0'),
            )
            totals[entry.worker_id] = totals.get(entry.worker_id, Decimal('0')) + payout
        else:
            monthly_rates.setdefault((entry.worker_id, entry.task_id), entry.pay_rate)
    for (worker_id, _task_id), rate in monthly_rates.items():
        totals[worker_id] = totals.get(worker_id, Decimal('0')) + rate
    return {
        worker_id: amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        for worker_id, amount in totals.items()
    }


def refresh_unpaid_worker_payroll(worker):
    cent = Decimal('0.01')
    worker_run_ids = PayrollLine.objects.filter(
        worker=worker,
        run__status=PayrollRun.Status.SCHEDULED,
    ).values('run_id')
    runs = PayrollRun.objects.select_for_update().filter(
        pk__in=worker_run_ids,
    ).order_by('period')
    for run in runs:
        line = PayrollLine.objects.select_for_update().get(run=run, worker=worker)
        year, month = map(int, run.period.split('-'))
        attendance = StaffAttendance.objects.filter(
            worker=worker,
            date__year=year,
            date__month=month,
            attended=True,
        ).aggregate(days_worked=Count('id'), gross=Sum('daily_wage'))
        hours = worker.hours_per_period if worker.pay_basis == StaffMember.PayBasis.HOURLY else Decimal('0')
        if worker.pay_basis == StaffMember.PayBasis.DAILY:
            base_gross = attendance['gross'] or Decimal('0.00')
        elif worker.pay_basis == StaffMember.PayBasis.MONTHLY:
            base_gross = worker.pay_rate
        else:
            base_gross = worker.pay_rate * hours
        gross = (base_gross + line.task_pay).quantize(cent, rounding=ROUND_HALF_UP)
        withholding = (gross * worker.withholding_percent / Decimal('100')).quantize(cent, rounding=ROUND_HALF_UP)
        benefits = min(worker.benefit_deduction, gross) if worker.pay_basis == StaffMember.PayBasis.DAILY else worker.benefit_deduction
        if withholding + benefits > gross:
            raise ValidationError({'worker': f'Deductions exceed gross pay for {worker.employee_number}.'})
        line.pay_basis = worker.pay_basis
        line.hours = hours
        line.days_worked = attendance['days_worked']
        line.gross_pay = gross
        line.withholding = withholding
        line.benefits = benefits
        line.net_pay = gross - withholding - benefits
        line.save(update_fields=[
            'pay_basis', 'hours', 'days_worked', 'gross_pay', 'withholding', 'benefits', 'net_pay',
        ])
        totals = run.lines.aggregate(
            gross_total=Sum('gross_pay'),
            withholding_total=Sum('withholding'),
            benefits_total=Sum('benefits'),
            net_total=Sum('net_pay'),
        )
        run.gross_total = totals['gross_total'] or Decimal('0.00')
        run.withholding_total = totals['withholding_total'] or Decimal('0.00')
        run.benefits_total = totals['benefits_total'] or Decimal('0.00')
        run.net_total = totals['net_total'] or Decimal('0.00')
        run.save(update_fields=['gross_total', 'withholding_total', 'benefits_total', 'net_total'])


class StaffMemberViewSet(viewsets.ModelViewSet):
    queryset = StaffMember.objects.all()
    serializer_class = StaffMemberSerializer
    permission_classes = [RoleModelPermissions]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['employee_number', 'full_name', 'job_title', 'department', 'email']
    ordering_fields = ['full_name', 'department', 'hire_date', 'pay_rate']
    ordering = ['full_name']

    def perform_create(self, serializer):
        worker = serializer.save()
        SecurityAuditEvent.objects.create(
            actor=self.request.user,
            action='staff.created',
            target_type='staff_member',
            target_id=worker.employee_number,
            details={'full_name': worker.full_name, 'department': worker.department},
        )

    @transaction.atomic
    def perform_update(self, serializer):
        worker = serializer.save()
        compensation_fields = {'pay_basis', 'pay_rate', 'hours_per_period', 'withholding_percent', 'benefit_deduction'}
        if compensation_fields.intersection(serializer.validated_data):
            refresh_unpaid_worker_payroll(worker)
        SecurityAuditEvent.objects.create(
            actor=self.request.user,
            action='staff.updated',
            target_type='staff_member',
            target_id=worker.employee_number,
            details={'full_name': worker.full_name, 'updated_fields': sorted(serializer.validated_data.keys())},
        )


class StaffTaskViewSet(viewsets.ModelViewSet):
    queryset = StaffTask.objects.all()
    serializer_class = StaffTaskSerializer
    permission_classes = [RoleModelPermissions]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def perform_create(self, serializer):
        task = serializer.save()
        SecurityAuditEvent.objects.create(
            actor=self.request.user,
            action='staff.task_created',
            target_type='staff_task',
            target_id=str(task.id),
            details={
                'name': task.name,
                'pay_basis': task.pay_basis,
                'pay_rate': str(task.pay_rate),
                'target_tiers': task.target_tiers,
            },
        )

    @transaction.atomic
    def perform_update(self, serializer):
        updated_fields = set(serializer.validated_data)
        task = serializer.save()
        if not task.is_active:
            StaffTaskAssignment.objects.filter(task=task, is_active=True).update(is_active=False)
        if updated_fields.intersection({'name', 'pay_rate', 'target_tiers'}):
            payroll_periods = set(PayrollRun.objects.values_list('period', flat=True))
            entry_periods = StaffTaskEntry.objects.filter(task=task).dates('date', 'month')
            for month_start in entry_periods:
                period = month_start.strftime('%Y-%m')
                if period in payroll_periods:
                    continue
                StaffTaskEntry.objects.filter(
                    task=task,
                    date__year=month_start.year,
                    date__month=month_start.month,
                ).update(
                    task_name=task.name,
                    pay_rate=task.pay_rate,
                    target_tiers=task.target_tiers,
                )
        SecurityAuditEvent.objects.create(
            actor=self.request.user,
            action='staff.task_updated',
            target_type='staff_task',
            target_id=str(task.id),
            details={'name': task.name, 'updated_fields': sorted(serializer.validated_data.keys())},
        )


def record_permanent_task_entries(worker, work_date, attended, user):
    if not attended:
        StaffTaskEntry.objects.filter(
            worker=worker,
            date=work_date,
        ).delete()
        refresh_daily_attendance_wage(worker, work_date)
        return

    assignments = StaffTaskAssignment.objects.filter(
        worker=worker,
        is_active=True,
        assigned_from__lte=work_date,
        task__is_active=True,
    ).select_related('task')
    for assignment in assignments:
        task = assignment.task
        entry = StaffTaskEntry.objects.filter(worker=worker, task=task, date=work_date).first()
        if entry:
            if entry.assignment_type != StaffTaskEntry.AssignmentType.PERMANENT:
                entry.assignment_type = StaffTaskEntry.AssignmentType.PERMANENT
                entry.save(update_fields=['assignment_type'])
            continue
        StaffTaskEntry.objects.create(
            worker=worker,
            task=task,
            date=work_date,
            assignment_type=StaffTaskEntry.AssignmentType.PERMANENT,
            task_name=task.name,
            pay_basis=task.pay_basis,
            pay_rate=task.pay_rate,
            target_tiers=task.target_tiers,
            recorded_by=user,
        )
    refresh_daily_attendance_wage(worker, work_date)


class StaffTaskAssignmentViewSet(viewsets.ModelViewSet):
    queryset = StaffTaskAssignment.objects.select_related('worker', 'task')
    serializer_class = StaffTaskAssignmentSerializer
    permission_classes = [RoleModelPermissions]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get('active') == 'true':
            queryset = queryset.filter(is_active=True)
        return queryset

    def perform_create(self, serializer):
        assignment = serializer.save()
        attended_records = StaffAttendance.objects.filter(
            worker=assignment.worker,
            attended=True,
            date__gte=assignment.assigned_from,
            date__lte=timezone.localdate(),
        )
        for attendance in attended_records:
            if not PayrollRun.objects.filter(period=attendance.date.strftime('%Y-%m')).exists():
                record_permanent_task_entries(assignment.worker, attendance.date, True, self.request.user)
        SecurityAuditEvent.objects.create(
            actor=self.request.user,
            action='staff.task_assignment_created',
            target_type='staff_task_assignment',
            target_id=str(assignment.id),
            details={'worker': assignment.worker.full_name, 'task': assignment.task.name, 'assigned_from': assignment.assigned_from.isoformat()},
        )

    def perform_update(self, serializer):
        assignment = serializer.save()
        SecurityAuditEvent.objects.create(
            actor=self.request.user,
            action='staff.task_assignment_updated',
            target_type='staff_task_assignment',
            target_id=str(assignment.id),
            details={'worker': assignment.worker.full_name, 'task': assignment.task.name, 'is_active': assignment.is_active},
        )


class StaffTaskEntryViewSet(viewsets.ViewSet):
    permission_classes = [RoleModelPermissions]

    def list(self, request):
        period = request.query_params.get('period', '')
        try:
            parsed_period = datetime.strptime(period, '%Y-%m')
        except (TypeError, ValueError):
            raise ValidationError({'period': 'Enter a task work month in YYYY-MM format.'})
        if parsed_period.strftime('%Y-%m') != period:
            raise ValidationError({'period': 'Enter a task work month in YYYY-MM format.'})
        entries = StaffTaskEntry.objects.filter(
            date__year=parsed_period.year,
            date__month=parsed_period.month,
        ).select_related('worker', 'task')
        return Response(StaffTaskEntrySerializer(entries, many=True).data)

    @action(detail=False, methods=['post'])
    @transaction.atomic
    def remove_permanent(self, request):
        serializer = StaffTaskEntryRemovalInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        worker = serializer.validated_data['worker']
        task = serializer.validated_data['task']
        work_date = serializer.validated_data['date']
        if work_date > timezone.localdate():
            raise ValidationError({'date': 'Choose a task date that is not in the future.'})
        if PayrollRun.objects.filter(period=work_date.strftime('%Y-%m')).exists():
            raise ValidationError({'period': 'Task work is locked because payroll for this month has been generated.'})

        entry = StaffTaskEntry.objects.select_for_update().filter(
            worker=worker,
            task=task,
            date=work_date,
            assignment_type=StaffTaskEntry.AssignmentType.PERMANENT,
        ).first()
        if entry is None:
            raise ValidationError({'task': 'The permanent task record could not be found for this date.'})

        assignment = StaffTaskAssignment.objects.select_for_update().filter(
            worker=worker,
            task=task,
            is_active=True,
            assigned_from__lte=work_date,
        ).first()
        if assignment:
            assignment.is_active = False
            assignment.save(update_fields=['is_active'])
            SecurityAuditEvent.objects.create(
                actor=request.user,
                action='staff.task_assignment_updated',
                target_type='staff_task_assignment',
                target_id=str(assignment.id),
                details={
                    'worker': worker.full_name,
                    'task': task.name,
                    'is_active': False,
                    'removed_on': work_date.isoformat(),
                },
            )

        entry.delete()
        refresh_daily_attendance_wage(worker, work_date)
        SecurityAuditEvent.objects.create(
            actor=request.user,
            action='staff.task_work_removed',
            target_type='staff_task_entry',
            target_id=f'{worker.id}:{task.id}:{work_date.isoformat()}',
            details={
                'worker': worker.full_name,
                'task': task.name,
                'date': work_date.isoformat(),
                'permanent_assignment_deactivated': bool(assignment),
            },
        )
        return Response({'removed': True, 'permanent_assignment_deactivated': bool(assignment)})

    @action(detail=False, methods=['post'])
    @transaction.atomic
    def record_day(self, request):
        date_value = request.data.get('date', '')
        try:
            work_date = datetime.strptime(date_value, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            raise ValidationError({'date': 'Enter a task date in YYYY-MM-DD format.'})
        if work_date.isoformat() != date_value or work_date > timezone.localdate():
            raise ValidationError({'date': 'Choose a valid task date that is not in the future.'})
        if PayrollRun.objects.filter(period=work_date.strftime('%Y-%m')).exists():
            raise ValidationError({'period': 'Task work is locked because payroll for this month has been generated.'})

        rows = request.data.get('records')
        if not isinstance(rows, list):
            raise ValidationError({'records': 'Submit a list of task assignments.'})
        serializer = StaffTaskEntryInputSerializer(data=rows, many=True)
        serializer.is_valid(raise_exception=True)
        missing_target_units = {
            index: {'units_worked': 'Enter the number of units completed for this task.'}
            for index, (submitted, row) in enumerate(zip(rows, serializer.validated_data))
            if row['task'].pay_basis == StaffTask.PayBasis.TARGET
            and 'units_worked' not in submitted
        }
        if missing_target_units:
            raise ValidationError({'records': missing_target_units})
        keys = [(row['worker'].id, row['task'].id) for row in serializer.validated_data]
        if len(keys) != len(set(keys)):
            raise ValidationError({'records': 'A worker can only be assigned to each task once per day.'})

        existing_entries = {
            (entry.worker_id, entry.task_id): entry
            for entry in StaffTaskEntry.objects.filter(date=work_date)
        }
        saved_entries = []
        submitted_keys = set(keys)
        for row in serializer.validated_data:
            worker = row['worker']
            task = row['task']
            if worker.status != StaffMember.Status.ACTIVE:
                raise ValidationError({'worker': f'{worker.full_name} must be an active worker.'})
            if worker.hire_date > work_date:
                raise ValidationError({'worker': f'{worker.full_name} was not employed on this task date.'})
            if not StaffAttendance.objects.filter(worker=worker, date=work_date, attended=True).exists():
                raise ValidationError({'worker': f'{worker.full_name} must be marked attended before a task can be recorded.'})
            existing = existing_entries.get((worker.id, task.id))
            if not task.is_active and existing is None:
                raise ValidationError({'task': f'{task.name} is inactive and cannot receive new work assignments.'})
            if existing:
                existing.hours = row['hours']
                existing.units_worked = row['units_worked']
                existing.recorded_by = request.user
                existing.save(update_fields=['hours', 'units_worked', 'recorded_by'])
                saved_entries.append(existing)
            else:
                saved_entries.append(StaffTaskEntry.objects.create(
                    worker=worker,
                    task=task,
                    date=work_date,
                    task_name=task.name,
                    pay_basis=task.pay_basis,
                    pay_rate=task.pay_rate,
                    hours=row['hours'],
                    target_tiers=task.target_tiers,
                    units_worked=row['units_worked'],
                    recorded_by=request.user,
                ))
        for worker_id, task_id in existing_entries.keys() - submitted_keys:
            if existing_entries[(worker_id, task_id)].assignment_type == StaffTaskEntry.AssignmentType.PERMANENT:
                continue
            StaffTaskEntry.objects.filter(
                date=work_date,
                worker_id=worker_id,
                task_id=task_id,
            ).delete()

        affected_worker_ids = {worker_id for worker_id, _task_id in existing_entries}
        affected_worker_ids.update(row['worker'].id for row in serializer.validated_data)
        for worker in StaffMember.objects.filter(id__in=affected_worker_ids):
            refresh_daily_attendance_wage(worker, work_date)

        SecurityAuditEvent.objects.create(
            actor=request.user,
            action='staff.task_work_recorded',
            target_type='staff_task_entry',
            target_id=work_date.isoformat(),
            details={'assignments_recorded': len(saved_entries)},
        )
        return Response(StaffTaskEntrySerializer(saved_entries, many=True).data)


class StaffAttendanceViewSet(viewsets.ViewSet):
    permission_classes = [RoleModelPermissions]

    def list(self, request):
        period = request.query_params.get('period', '')
        if period:
            try:
                parsed_period = datetime.strptime(period, '%Y-%m')
            except (TypeError, ValueError):
                raise ValidationError({'period': 'Enter an attendance month in YYYY-MM format.'})
            if parsed_period.strftime('%Y-%m') != period:
                raise ValidationError({'period': 'Enter an attendance month in YYYY-MM format.'})
            records = StaffAttendance.objects.filter(date__year=parsed_period.year, date__month=parsed_period.month).select_related('worker')
            return Response(StaffAttendanceSerializer(records, many=True).data)

        date_value = request.query_params.get('date', '')
        try:
            attendance_date = datetime.strptime(date_value, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            raise ValidationError({'date': 'Enter an attendance date in YYYY-MM-DD format.'})
        if attendance_date.isoformat() != date_value:
            raise ValidationError({'date': 'Enter an attendance date in YYYY-MM-DD format.'})
        records = StaffAttendance.objects.filter(date=attendance_date).select_related('worker')
        return Response(StaffAttendanceSerializer(records, many=True).data)

    @action(detail=False, methods=['post'])
    @transaction.atomic
    def record_day(self, request):
        date_value = request.data.get('date', '')
        try:
            attendance_date = datetime.strptime(date_value, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            raise ValidationError({'date': 'Enter an attendance date in YYYY-MM-DD format.'})
        if attendance_date.isoformat() != date_value or attendance_date > timezone.localdate():
            raise ValidationError({'date': 'Choose a valid date that is not in the future.'})
        if PayrollRun.objects.filter(period=attendance_date.strftime('%Y-%m')).exists():
            raise ValidationError({'period': 'Attendance is locked because payroll for this month has been generated.'})
        records_data = request.data.get('records')
        if not isinstance(records_data, list) or not records_data:
            raise ValidationError({'records': 'Add at least one worker attendance record.'})
        serializer = StaffAttendanceInputSerializer(data=records_data, many=True)
        serializer.is_valid(raise_exception=True)
        worker_ids = [row['worker'].id for row in serializer.validated_data]
        if len(worker_ids) != len(set(worker_ids)):
            raise ValidationError({'records': 'A worker can only be recorded once per day.'})

        workers_by_id = {row['worker'].id: row['worker'] for row in serializer.validated_data}
        for worker in workers_by_id.values():
            if worker.status != StaffMember.Status.ACTIVE:
                raise ValidationError({'worker': f'{worker.full_name} must be an active worker.'})

        attendance_rows = []
        for row in serializer.validated_data:
            worker = row['worker']
            attended = row['attended']
            output_quantity = row['output_quantity']
            attendance_rows.append(StaffAttendance(
                worker=worker,
                date=attendance_date,
                attended=attended,
                output_quantity=output_quantity,
                daily_wage_override=row['daily_wage_override'],
                daily_wage=daily_attendance_wage(
                    attendance_date,
                    attended,
                    output_quantity,
                    row['daily_wage_override'],
                ) if worker.pay_basis == StaffMember.PayBasis.DAILY else Decimal('0.00'),
                recorded_by=request.user,
            ))

        if attendance_rows:
            StaffAttendance.objects.bulk_create(
                attendance_rows,
                update_conflicts=True,
                update_fields=[
                    'attended',
                    'output_quantity',
                    'daily_wage_override',
                    'daily_wage',
                    'recorded_by',
                    'updated_at',
                ],
                unique_fields=['worker', 'date'],
            )

        worker_ids = list(workers_by_id)
        attended_worker_ids = [
            row['worker'].id for row in serializer.validated_data if row['attended']
        ]
        absent_worker_ids = list(set(worker_ids) - set(attended_worker_ids))
        if absent_worker_ids:
            StaffTaskEntry.objects.filter(
                worker_id__in=absent_worker_ids,
                date=attendance_date,
            ).delete()

        existing_entries = {
            (entry.worker_id, entry.task_id): entry
            for entry in StaffTaskEntry.objects.filter(
                worker_id__in=attended_worker_ids,
                date=attendance_date,
            )
        }
        assignments = StaffTaskAssignment.objects.filter(
            worker_id__in=attended_worker_ids,
            is_active=True,
            assigned_from__lte=attendance_date,
            task__is_active=True,
        ).select_related('worker', 'task')
        entries_to_create = []
        entries_to_update = []
        for assignment in assignments:
            task = assignment.task
            key = (assignment.worker_id, task.id)
            existing = existing_entries.get(key)
            if existing:
                if existing.assignment_type != StaffTaskEntry.AssignmentType.PERMANENT:
                    existing.assignment_type = StaffTaskEntry.AssignmentType.PERMANENT
                    entries_to_update.append(existing)
                continue
            entries_to_create.append(StaffTaskEntry(
                worker=assignment.worker,
                task=task,
                date=attendance_date,
                assignment_type=StaffTaskEntry.AssignmentType.PERMANENT,
                task_name=task.name,
                pay_basis=task.pay_basis,
                pay_rate=task.pay_rate,
                target_tiers=task.target_tiers,
                recorded_by=request.user,
            ))

        if entries_to_update:
            StaffTaskEntry.objects.bulk_update(entries_to_update, ['assignment_type'])
        if entries_to_create:
            StaffTaskEntry.objects.bulk_create(entries_to_create)

        workers_with_task_entries = set(StaffTaskEntry.objects.filter(
            worker_id__in=worker_ids,
            date=attendance_date,
        ).values_list('worker_id', flat=True))
        saved_records = list(StaffAttendance.objects.filter(
            worker_id__in=worker_ids,
            date=attendance_date,
        ).select_related('worker'))
        for attendance in saved_records:
            if attendance.worker.pay_basis == StaffMember.PayBasis.DAILY:
                attendance.daily_wage = (
                    daily_attendance_wage(
                        attendance_date,
                        True,
                        attendance.output_quantity,
                        attendance.daily_wage_override,
                    )
                    if attendance.attended and attendance.worker_id not in workers_with_task_entries
                    else Decimal('0.00')
                )
        StaffAttendance.objects.bulk_update(saved_records, ['daily_wage'])

        SecurityAuditEvent.objects.create(
            actor=request.user,
            action='staff.attendance_recorded',
            target_type='staff_attendance',
            target_id=attendance_date.isoformat(),
            details={'workers_recorded': len(attendance_rows)},
        )
        return Response(StaffAttendanceSerializer(saved_records, many=True).data)


@api_view(['GET'])
@permission_classes([RoleModelPermissions])
def staff_dashboard(request):
    current_period = request.query_params.get('period') or timezone.localdate().strftime('%Y-%m')
    try:
        parsed_period = datetime.strptime(current_period, '%Y-%m')
    except (TypeError, ValueError):
        raise ValidationError({'period': 'Enter a payroll period in YYYY-MM format.'})
    if parsed_period.strftime('%Y-%m') != current_period:
        raise ValidationError({'period': 'Enter a payroll period in YYYY-MM format.'})
    workers = StaffMember.objects.all()
    active_workers = list(workers.filter(status=StaffMember.Status.ACTIVE))
    current_run = PayrollRun.objects.filter(period=current_period).prefetch_related('lines').first()
    cent = Decimal('0.01')
    attendance_totals = {
        row['worker_id']: {'days_worked': row['days_worked'], 'gross': row['gross'] or Decimal('0.00')}
        for row in StaffAttendance.objects.filter(date__year=parsed_period.year, date__month=parsed_period.month, attended=True)
        .values('worker_id')
        .annotate(days_worked=Count('id'), gross=Sum('daily_wage'))
    }
    task_entries = list(StaffTaskEntry.objects.filter(
        date__year=parsed_period.year,
        date__month=parsed_period.month,
    ).select_related('task').order_by('date', 'id'))
    period_task_pay = task_pay_totals(task_entries)

    def estimate(worker):
        if worker.pay_basis == StaffMember.PayBasis.DAILY:
            base_gross = attendance_totals.get(worker.id, {}).get('gross', Decimal('0.00'))
        else:
            base_gross = worker.pay_rate if worker.pay_basis == StaffMember.PayBasis.MONTHLY else worker.pay_rate * worker.hours_per_period
        task_pay = period_task_pay.get(worker.id, Decimal('0.00'))
        gross = (base_gross + task_pay).quantize(cent, rounding=ROUND_HALF_UP)
        withholding = (gross * worker.withholding_percent / Decimal('100')).quantize(cent, rounding=ROUND_HALF_UP)
        benefits = min(worker.benefit_deduction, gross) if worker.pay_basis == StaffMember.PayBasis.DAILY else worker.benefit_deduction
        return gross, withholding, benefits, gross - withholding - benefits, task_pay

    preview = [estimate(worker) for worker in active_workers]
    summary = {
        'current_period': current_period,
        'active_workers': len(active_workers),
        'on_leave_workers': workers.filter(status=StaffMember.Status.LEAVE).count(),
        'inactive_workers': workers.filter(status=StaffMember.Status.INACTIVE).count(),
        'gross_total': current_run.gross_total if current_run else sum((row[0] for row in preview), Decimal('0')),
        'task_pay_total': (
            sum((line.task_pay for line in current_run.lines.all()), Decimal('0'))
            if current_run
            else sum((row[4] for row in preview), Decimal('0'))
        ),
        'withholding_total': current_run.withholding_total if current_run else sum((row[1] for row in preview), Decimal('0')),
        'benefits_total': current_run.benefits_total if current_run else sum((row[2] for row in preview), Decimal('0')),
        'net_total': current_run.net_total if current_run else sum((row[3] for row in preview), Decimal('0')),
        'run_status': current_run.status if current_run else 'draft',
        'run_id': current_run.id if current_run else None,
        'run_count': PayrollRun.objects.count(),
    }
    departments = []
    for department in sorted({worker.department for worker in active_workers}):
        members = [worker for worker in active_workers if worker.department == department]
        total = sum((estimate(worker)[0] for worker in members), Decimal('0'))
        departments.append({'name': department, 'workers': len(members), 'gross_total': total})

    return Response({
        'summary': summary,
        'workers': StaffMemberSerializer(
            workers,
            many=True,
            context={'attendance_totals': attendance_totals, 'task_pay_totals': period_task_pay},
        ).data,
        'departments': departments,
        'payroll_runs': PayrollRunSerializer(PayrollRun.objects.prefetch_related('lines')[:12], many=True).data,
    })


class PayrollRunViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PayrollRun.objects.prefetch_related('lines').all()
    serializer_class = PayrollRunSerializer
    permission_classes = [RoleModelPermissions]

    @action(detail=False, methods=['post'])
    @transaction.atomic
    def generate(self, request):
        period = request.data.get('period', '')
        try:
            parsed_period = datetime.strptime(period, '%Y-%m')
        except (TypeError, ValueError):
            raise ValidationError({'period': 'Enter a payroll period in YYYY-MM format.'})
        if parsed_period.strftime('%Y-%m') != period:
            raise ValidationError({'period': 'Enter a payroll period in YYYY-MM format.'})
        if PayrollRun.objects.filter(period=period).exists():
            raise ValidationError({'period': 'A payroll run already exists for this period.'})

        workers = list(StaffMember.objects.select_for_update().filter(status=StaffMember.Status.ACTIVE).order_by('id'))
        if not workers:
            raise ValidationError({'workers': 'Add at least one active worker before generating payroll.'})

        cent = Decimal('0.01')
        attendance_totals = {
            row['worker_id']: {'days_worked': row['days_worked'], 'gross': row['gross'] or Decimal('0.00')}
            for row in StaffAttendance.objects.filter(date__year=parsed_period.year, date__month=parsed_period.month, attended=True)
            .values('worker_id')
            .annotate(days_worked=Count('id'), gross=Sum('daily_wage'))
        }
        task_entries = list(StaffTaskEntry.objects.filter(
            date__year=parsed_period.year,
            date__month=parsed_period.month,
        ).select_related('task').order_by('date', 'id'))
        task_pay_by_worker = task_pay_totals(task_entries)
        run = PayrollRun.objects.create(period=period, worker_count=len(workers), created_by=request.user)
        lines = []
        for worker in workers:
            hours = worker.hours_per_period if worker.pay_basis == StaffMember.PayBasis.HOURLY else Decimal('0')
            days_worked = attendance_totals.get(worker.id, {}).get('days_worked', 0)
            if worker.pay_basis == StaffMember.PayBasis.DAILY:
                base_gross = attendance_totals.get(worker.id, {}).get('gross', Decimal('0.00'))
            else:
                base_gross = worker.pay_rate if worker.pay_basis == StaffMember.PayBasis.MONTHLY else worker.pay_rate * hours
            task_pay = task_pay_by_worker.get(worker.id, Decimal('0.00'))
            gross = (base_gross + task_pay).quantize(cent, rounding=ROUND_HALF_UP)
            withholding = (gross * worker.withholding_percent / Decimal('100')).quantize(cent, rounding=ROUND_HALF_UP)
            benefits = min(worker.benefit_deduction, gross) if worker.pay_basis == StaffMember.PayBasis.DAILY else worker.benefit_deduction
            if withholding + benefits > gross:
                raise ValidationError({'worker': f'Deductions exceed gross pay for {worker.employee_number}.'})
            lines.append(PayrollLine(
                run=run,
                worker=worker,
                employee_number=worker.employee_number,
                worker_name=worker.full_name,
                job_title=worker.job_title,
                department=worker.department,
                pay_basis=worker.pay_basis,
                hours=hours,
                days_worked=days_worked,
                task_pay=task_pay,
                gross_pay=gross,
                withholding=withholding,
                benefits=benefits,
                net_pay=gross - withholding - benefits,
            ))
        PayrollLine.objects.bulk_create(lines)
        run.gross_total = sum((line.gross_pay for line in lines), Decimal('0'))
        run.withholding_total = sum((line.withholding for line in lines), Decimal('0'))
        run.benefits_total = sum((line.benefits for line in lines), Decimal('0'))
        run.net_total = sum((line.net_pay for line in lines), Decimal('0'))
        run.save(update_fields=['gross_total', 'withholding_total', 'benefits_total', 'net_total'])
        SecurityAuditEvent.objects.create(
            actor=request.user,
            action='payroll.generated',
            target_type='payroll_run',
            target_id=period,
            details={'worker_count': run.worker_count, 'gross_total': str(run.gross_total), 'net_total': str(run.net_total)},
        )
        return Response(PayrollRunSerializer(run).data, status=201)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def mark_paid(self, request, pk=None):
        run = PayrollRun.objects.select_for_update().get(pk=pk)
        if run.status == PayrollRun.Status.PAID:
            raise ValidationError({'status': 'This payroll run is already marked paid.'})
        run.status = PayrollRun.Status.PAID
        run.paid_at = timezone.now()
        run.save(update_fields=['status', 'paid_at'])
        SecurityAuditEvent.objects.create(
            actor=request.user,
            action='payroll.marked_paid',
            target_type='payroll_run',
            target_id=run.period,
            details={'net_total': str(run.net_total)},
        )
        return Response(PayrollRunSerializer(run).data)

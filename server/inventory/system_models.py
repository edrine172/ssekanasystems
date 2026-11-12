from django.db import models
from .catalog_models import Category


class SecurityAuditEvent(models.Model):
    actor = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='inventory_security_events')
    action = models.CharField(max_length=80)
    target_type = models.CharField(max_length=80)
    target_id = models.CharField(max_length=80, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        permissions = [('manage_access', 'Can manage workspace access')]
        indexes = [
            models.Index(fields=['-created_at'], name='sec_audit_created_idx'),
            models.Index(fields=['target_type', '-created_at'], name='sec_audit_target_created_idx'),
        ]

    def __str__(self):
        return f'{self.action} · {self.target_type} {self.target_id}'


class SystemSetting(models.Model):
    key = models.CharField(max_length=80, unique=True)
    value = models.JSONField()
    category = models.CharField(max_length=40)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='inventory_settings_changes')

    class Meta:
        ordering = ['category', 'key']

    def __str__(self):
        return f'{self.category}.{self.key}'


class Notification(models.Model):
    class Category(models.TextChoices):
        STOCK = 'stock', 'Stock alerts'
        PROCUREMENT = 'procurement', 'Procurement'
        BILLING = 'billing', 'Billing and sales'
        OPERATIONS = 'operations', 'Operations'

    class Severity(models.TextChoices):
        INFO = 'info', 'Information'
        WARNING = 'warning', 'Warning'
        CRITICAL = 'critical', 'Critical'

    source_key = models.CharField(max_length=140, unique=True)
    category = models.CharField(max_length=16, choices=Category.choices)
    severity = models.CharField(max_length=12, choices=Severity.choices, default=Severity.INFO)
    title = models.CharField(max_length=160)
    message = models.TextField()
    target_label = models.CharField(max_length=120, blank=True)
    dashboard = models.CharField(max_length=24)
    is_read = models.BooleanField(default=False)
    is_dismissed = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_active', 'is_dismissed', '-created_at'], name='notification_active_recent_idx'),
        ]

    def __str__(self):
        return self.title

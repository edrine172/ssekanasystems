import json
from math import isfinite
import re
from urllib.error import URLError
from urllib.request import urlopen
from django.core.cache import cache
from django.db import transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from .models import SecurityAuditEvent, SystemSetting
from .permissions import RoleModelPermissions


SETTINGS_DEFAULTS = {
    'organization': {
        'business_name': 'Apex Supply Co.',
        'tax_id': '',
        'currency': 'UGX',
        'timezone': 'Africa/Kampala',
        'default_warehouse': 'Main Warehouse',
    },
    'operations': {
        'reorder_threshold': 15,
        'allow_negative_stock': True,
        'auto_purchase_drafts': True,
        'default_payment_terms': 'Net 30',
    },
    'security': {
        'require_two_factor': False,
        'session_timeout_minutes': 30,
        'audit_retention_days': 365,
    },
    'integrations': {
        'quickbooks_enabled': True,
        'stripe_enabled': True,
        'webhooks_enabled': True,
    },
}


@api_view(['GET', 'PATCH'])
@permission_classes([RoleModelPermissions])
def system_settings(request):
    settings = {category: values.copy() for category, values in SETTINGS_DEFAULTS.items()}
    for item in SystemSetting.objects.all():
        if item.category in settings and item.key in settings[item.category]:
            settings[item.category][item.key] = item.value

    if request.method == 'PATCH':
        updates = request.data.get('settings')
        if not isinstance(updates, dict) or not updates:
            raise ValidationError({'settings': 'Provide at least one category of settings to update.'})

        validated = []
        for category, values in updates.items():
            if category not in SETTINGS_DEFAULTS or not isinstance(values, dict) or not values:
                raise ValidationError({'settings': f'Unknown or empty settings category: {category}.'})
            for key, value in values.items():
                if key not in SETTINGS_DEFAULTS[category]:
                    raise ValidationError({'settings': f'Unknown setting: {category}.{key}.'})
                if category == 'organization' and key == 'currency' and (
                    not isinstance(value, str) or not re.fullmatch(r'[A-Z]{3}', value)
                ):
                    raise ValidationError({'settings': 'Currency must be a three-letter uppercase currency code.'})
                default = SETTINGS_DEFAULTS[category][key]
                if type(value) is not type(default):
                    raise ValidationError({'settings': f'{category}.{key} has an invalid value type.'})
                if isinstance(value, str) and len(value) > 120:
                    raise ValidationError({'settings': f'{category}.{key} must be 120 characters or fewer.'})
                if isinstance(value, int) and not isinstance(value, bool) and value < 1:
                    raise ValidationError({'settings': f'{category}.{key} must be greater than zero.'})
                validated.append((category, key, value))

        with transaction.atomic():
            for category, key, value in validated:
                previous = settings[category][key]
                if previous == value:
                    continue
                SystemSetting.objects.update_or_create(
                    key=key,
                    defaults={'category': category, 'value': value, 'updated_by': request.user if request.user.is_authenticated else None},
                )
                SecurityAuditEvent.objects.create(
                    actor=request.user if request.user.is_authenticated else None,
                    action='settings.updated',
                    target_type='settings',
                    target_id=f'{category}.{key}',
                    details={'previous': previous, 'value': value},
                )
                settings[category][key] = value

    audit_log = [
        {
            'id': event.id,
            'actor_name': event.actor.get_full_name() or event.actor.get_username() if event.actor else 'System',
            'action': event.action,
            'target_id': event.target_id,
            'details': event.details,
            'created_at': event.created_at,
        }
        for event in SecurityAuditEvent.objects.filter(target_type='settings').select_related('actor')[:20]
    ]
    return Response({'settings': settings, 'audit_log': audit_log})


@api_view(['GET'])
@permission_classes([AllowAny])
def exchange_rates(request):
    cached_rates = cache.get('ugx_exchange_rates')
    if cached_rates is None:
        try:
            with urlopen('https://open.er-api.com/v6/latest/UGX', timeout=5) as response:
                payload = json.load(response)
        except (URLError, TimeoutError, OSError, ValueError):
            return Response({'detail': 'Live UGX exchange rates are temporarily unavailable.'}, status=503)

        raw_rates = payload.get('rates') if isinstance(payload, dict) and payload.get('result') == 'success' and payload.get('base_code') == 'UGX' else None
        updated_at = payload.get('time_last_update_utc') if isinstance(payload, dict) else None
        if not isinstance(raw_rates, dict) or not isinstance(updated_at, str):
            return Response({'detail': 'The exchange-rate service returned an invalid response.'}, status=502)

        rates = {
            code: rate
            for code, rate in raw_rates.items()
            if isinstance(code, str)
            and re.fullmatch(r'[A-Z]{3}', code)
            and isinstance(rate, (int, float))
            and not isinstance(rate, bool)
            and isfinite(rate)
            and rate > 0
        }
        rates['UGX'] = 1
        cached_rates = {'rates': rates, 'updated_at': updated_at}
        cache.set('ugx_exchange_rates', cached_rates, timeout=3600)

    configured_currency = SystemSetting.objects.filter(category='organization', key='currency').values_list('value', flat=True).first() or 'UGX'
    return Response({
        'base_currency': 'UGX',
        'currency': configured_currency,
        'rates': cached_rates['rates'],
        'updated_at': cached_rates['updated_at'],
    })

from datetime import timezone as datetime_timezone
import gzip
import json
import os
import tempfile
from io import BytesIO, StringIO, TextIOWrapper
from tempfile import SpooledTemporaryFile

from django.apps import apps
from django.core import serializers
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.serializers.base import DeserializationError
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, router, transaction
from django.http import FileResponse
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission

MAX_BACKUP_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_BACKUP_JSON_BYTES = 100 * 1024 * 1024
BACKUP_QUERY_CHUNK_SIZE = 100


class IsActiveSuperuser(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.is_staff and user.is_superuser)


def _database_objects():
    for app_config in apps.get_app_configs():
        if app_config.models_module is None:
            continue
        for model in app_config.get_models():
            if model._meta.proxy or not router.allow_migrate_model('default', model):
                continue
            if model._meta.app_label == 'sessions':
                continue
            queryset = model._default_manager.using('default').order_by(model._meta.pk.name)
            yield from queryset.iterator(chunk_size=BACKUP_QUERY_CHUNK_SIZE)


def _create_database_snapshot():
    backup_file = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode='w+b')
    use_repeatable_read = connection.vendor == 'postgresql' and not connection.in_atomic_block
    try:
        with transaction.atomic():
            if use_repeatable_read:
                with connection.cursor() as cursor:
                    cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            with gzip.GzipFile(fileobj=backup_file, mode='wb', compresslevel=1, mtime=0) as compressed:
                with TextIOWrapper(compressed, encoding='utf-8') as fixture:
                    serializers.serialize('json', _database_objects(), stream=fixture)
        backup_file.seek(0)
        return backup_file
    except Exception:
        backup_file.close()
        raise


def _timestamp():
    return timezone.now().astimezone(datetime_timezone.utc).strftime('%Y%m%dT%H%M%SZ')


@api_view(['GET'])
@permission_classes([IsActiveSuperuser])
def download_database_backup(request):
    backup_file = _create_database_snapshot()
    response = FileResponse(
        backup_file,
        as_attachment=True,
        filename=f'stockpulse-database-backup-{_timestamp()}.json.gz',
        content_type='application/gzip',
    )
    return _set_private_download_headers(response)


def _set_private_download_headers(response):
    response['Cache-Control'] = 'private, no-store, max-age=0'
    response['Pragma'] = 'no-cache'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def _read_backup(uploaded_file):
    if uploaded_file.size > MAX_BACKUP_UPLOAD_BYTES:
        raise ValidationError({'backup': 'Backup file must be 50 MB or smaller.'})

    raw = uploaded_file.read(MAX_BACKUP_UPLOAD_BYTES + 1)
    if len(raw) > MAX_BACKUP_UPLOAD_BYTES:
        raise ValidationError({'backup': 'Backup file must be 50 MB or smaller.'})
    try:
        if raw.startswith(b'\x1f\x8b'):
            with gzip.GzipFile(fileobj=BytesIO(raw)) as compressed:
                raw = compressed.read(MAX_BACKUP_JSON_BYTES + 1)
                if len(raw) > MAX_BACKUP_JSON_BYTES:
                    raise ValidationError({'backup': 'Uncompressed backup must be 100 MB or smaller.'})
        elif len(raw) > MAX_BACKUP_JSON_BYTES:
            raise ValidationError({'backup': 'Uncompressed backup must be 100 MB or smaller.'})
        fixture_data = json.loads(raw.decode('utf-8'))
    except (gzip.BadGzipFile, EOFError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError({'backup': 'Select a valid StockPulse JSON or .json.gz database backup.'}) from exc

    if not isinstance(fixture_data, list) or not fixture_data:
        raise ValidationError({'backup': 'The backup must contain a non-empty Django JSON fixture.'})
    for row in fixture_data:
        if not isinstance(row, dict) or not isinstance(row.get('model'), str) or not isinstance(row.get('fields'), dict):
            raise ValidationError({'backup': 'The backup contains an invalid database fixture record.'})

    user_model_label = get_user_model()._meta.label_lower
    if not any(
        row['model'] == user_model_label
        and row['fields'].get('is_active') is True
        and row['fields'].get('is_staff') is True
        and row['fields'].get('is_superuser') is True
        for row in fixture_data
    ):
        raise ValidationError({'backup': 'The backup must include at least one active Django superuser account.'})

    fixture_text = json.dumps(fixture_data, ensure_ascii=False)
    try:
        for _ in serializers.deserialize('json', fixture_text, ignorenonexistent=False):
            pass
    except (DeserializationError, LookupError, TypeError, ValueError) as exc:
        raise ValidationError({'backup': f'The backup contains invalid or incompatible records: {exc}'}) from exc
    return fixture_text, len(fixture_data)


@api_view(['POST'])
@permission_classes([IsActiveSuperuser])
def restore_database_backup(request):
    uploaded_file = request.FILES.get('backup')
    if uploaded_file is None:
        raise ValidationError({'backup': 'Select a database backup file to restore.'})

    fixture_text, restored_records = _read_backup(uploaded_file)
    safety_backup = _create_database_snapshot()
    fixture_path = None
    restore_succeeded = False
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.json', delete=False) as fixture:
            fixture_path = fixture.name
            fixture.write(fixture_text)
        if os.name != 'nt':
            os.chmod(fixture_path, 0o600)

        try:
            with transaction.atomic():
                call_command(
                    'flush',
                    interactive=False,
                    inhibit_post_migrate=True,
                    verbosity=0,
                )
                call_command(
                    'loaddata',
                    fixture_path,
                    format='json',
                    verbosity=0,
                    stdout=StringIO(),
                    stderr=StringIO(),
                )
            restore_succeeded = True
        except (CommandError, DeserializationError, DatabaseError, OSError, ValueError) as exc:
            raise ValidationError({
                'backup': f'Restore failed; the current database was left unchanged. Check that the backup matches this application version. Details: {exc}'
            }) from exc
    finally:
        if fixture_path and os.path.exists(fixture_path):
            os.unlink(fixture_path)
        if not restore_succeeded:
            safety_backup.close()

    response = FileResponse(
        safety_backup,
        as_attachment=True,
        filename=f'stockpulse-pre-restore-safety-backup-{_timestamp()}.json.gz',
        content_type='application/gzip',
    )
    response['X-Restored-Record-Count'] = str(restored_records)
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store, max-age=0'
    response['Pragma'] = 'no-cache'
    return response

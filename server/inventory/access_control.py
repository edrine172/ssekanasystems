import json
import math
from json import JSONDecodeError

from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.models import Group, Permission
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.core.cache import cache
from django.contrib.sessions.models import Session
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from rest_framework import serializers, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken

from .models import SecurityAuditEvent
from .throttling import AtomicRateThrottle

User = get_user_model()
ACCESS_DASHBOARD_CACHE_KEY = 'access_dashboard_payload'
ACCESS_DASHBOARD_CACHE_TIMEOUT = 30


class AuthEndpointThrottle(AtomicRateThrottle):
    scope = 'auth_login'

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request),
        }


def _auth_rate_limit_response(request):
    throttle = AuthEndpointThrottle()
    if throttle.allow_request(request, None):
        return None
    response = JsonResponse({'detail': 'Too many authentication attempts. Try again later.'}, status=429)
    if retry_after := throttle.wait():
        response['Retry-After'] = str(math.ceil(retry_after))
    return response


def _authentication_response(request, user, status=200):
    refresh = RefreshToken.for_user(user)
    response = JsonResponse({
        'user': _user_payload(user),
        'csrf_token': get_token(request),
        'access_token': str(refresh.access_token),
    }, status=status)
    response.set_cookie(
        'stockpulse_refresh',
        str(refresh),
        max_age=int(api_settings.REFRESH_TOKEN_LIFETIME.total_seconds()),
        httponly=True,
        secure=not settings.DEBUG,
        samesite='None' if not settings.DEBUG else 'Lax',
        path='/api/access/token/refresh/',
    )
    return response


def _clear_refresh_cookie(response):
    response.delete_cookie(
        'stockpulse_refresh',
        path='/api/access/token/refresh/',
        samesite='None' if not settings.DEBUG else 'Lax',
    )
    return response


def _user_payload(user):
    return {
        'id': user.id,
        'username': user.get_username(),
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'display_name': user.get_full_name() or user.get_username(),
        'is_active': user.is_active,
        'is_staff': user.is_staff,
        'is_superuser': user.is_superuser,
        'last_login': user.last_login.isoformat() if user.last_login else None,
        'date_joined': user.date_joined.isoformat(),
        'groups': [{'id': group.id, 'name': group.name} for group in user.groups.all()],
    }


@ensure_csrf_cookie
@require_GET
def access_csrf(request):
    return JsonResponse({'csrf_token': get_token(request)})


@csrf_protect
@require_POST
def access_login(request):
    if rate_limited := _auth_rate_limit_response(request):
        return rate_limited
    try:
        data = json.loads(request.body or '{}')
    except JSONDecodeError:
        return JsonResponse({'detail': 'Invalid JSON body.'}, status=400)
    user = authenticate(request, username=data.get('username', ''), password=data.get('password', ''))
    if user is None or not user.is_active or not user.is_superuser:
        return JsonResponse({'detail': 'Administrator sign-in failed.'}, status=400)
    login(request, user)
    _audit(user, 'session.login', 'user', user.pk)
    return _authentication_response(request, user)


@csrf_protect
@require_POST
def access_token_refresh(request):
    if rate_limited := _auth_rate_limit_response(request):
        return rate_limited
    refresh_token = request.COOKIES.get('stockpulse_refresh')
    if not refresh_token:
        return JsonResponse({'detail': 'Refresh token is missing.'}, status=401)
    serializer = TokenRefreshSerializer(data={'refresh': refresh_token})
    if not serializer.is_valid():
        response = JsonResponse({'detail': 'Refresh token is invalid or expired.'}, status=401)
        return _clear_refresh_cookie(response)
    return JsonResponse({'access_token': serializer.validated_data['access']})


@api_view(['GET'])
@permission_classes([AllowAny])
def access_session(request):
    if not request.user.is_authenticated or not request.user.is_active or not request.user.is_staff:
        return JsonResponse({'detail': 'Workspace sign-in required.'}, status=401)
    return JsonResponse({'user': _user_payload(request.user)})


@csrf_protect
@require_POST
def access_logout(request):
    if not request.user.is_authenticated:
        return JsonResponse({'detail': 'Administrator sign-in required.'}, status=401)
    _audit(request.user, 'session.logout', 'user', request.user.pk)
    logout(request)
    return _clear_refresh_cookie(JsonResponse({'ok': True}))


@csrf_protect
@require_POST
def account_register(request):
    if rate_limited := _auth_rate_limit_response(request):
        return rate_limited
    try:
        data = json.loads(request.body or '{}')
    except JSONDecodeError:
        return JsonResponse({'detail': 'Invalid JSON body.'}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({'detail': 'Registration data must be an object.'}, status=400)

    username = str(data.get('username', '')).strip()
    email = str(data.get('email', '')).strip()
    password = str(data.get('password', ''))
    if not username or len(username) > 150:
        return JsonResponse({'username': 'Enter a username of 1 to 150 characters.'}, status=400)
    if len(password) < 8:
        return JsonResponse({'password': 'Password must be at least 8 characters.'}, status=400)
    if User.objects.filter(username=username).exists():
        return JsonResponse({'username': 'That username is already in use.'}, status=400)
    if email:
        try:
            validate_email(email)
        except DjangoValidationError:
            return JsonResponse({'email': 'Enter a valid email address.'}, status=400)

    user = User.objects.create_user(
        username=username,
        email=email,
        first_name=str(data.get('first_name', '')).strip()[:150],
        last_name=str(data.get('last_name', '')).strip()[:150],
        password=password,
        is_staff=True,
        is_superuser=False,
    )
    user.groups.add(_registered_user_group())
    login(request, user)
    _audit(user, 'session.registered', 'user', user.pk)
    return _authentication_response(request, user, status=201)


@csrf_protect
@require_POST
def account_login(request):
    if rate_limited := _auth_rate_limit_response(request):
        return rate_limited
    try:
        data = json.loads(request.body or '{}')
    except JSONDecodeError:
        return JsonResponse({'detail': 'Invalid JSON body.'}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({'detail': 'Login data must be an object.'}, status=400)
    user = authenticate(request, username=data.get('username', ''), password=data.get('password', ''))
    if user is None or not user.is_active or not (user.is_staff or user.is_superuser):
        return JsonResponse({'detail': 'Administrator sign-in failed.'}, status=400)
    login(request, user)
    _audit(user, 'session.login', 'user', user.pk)
    return _authentication_response(request, user)


@api_view(['GET'])
@permission_classes([AllowAny])
def account_session(request):
    if not request.user.is_authenticated or not request.user.is_active or not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'detail': 'Administrator sign-in is required.'}, status=401)
    return JsonResponse({'user': _user_payload(request.user)})


@csrf_protect
@require_POST
def account_logout(request):
    if not request.user.is_authenticated:
        return JsonResponse({'detail': 'Sign in is required.'}, status=401)
    _audit(request.user, 'session.logout', 'user', request.user.pk)
    logout(request)
    return _clear_refresh_cookie(JsonResponse({'ok': True}))


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        if not (
            request.user
            and request.user.is_authenticated
            and request.user.is_active
            and request.user.is_staff
        ):
            return False
        return request.user.is_superuser or request.user.has_perm('inventory.manage_access')


def _registered_user_group():
    group, _ = Group.objects.get_or_create(name='Dashboard viewers')
    group.permissions.add(*Permission.objects.filter(
        content_type__app_label='inventory',
        codename__startswith='view_',
    ))
    return group


class SecurityAuditSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    def get_actor_name(self, event):
        return event.actor.get_full_name() or event.actor.get_username() if event.actor else 'System'

    class Meta:
        model = SecurityAuditEvent
        fields = ['id', 'actor_name', 'action', 'target_type', 'target_id', 'details', 'created_at']


class AccessUserSerializer(serializers.ModelSerializer):
    groups = serializers.PrimaryKeyRelatedField(queryset=Group.objects.all(), many=True, required=False)
    group_names = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False, min_length=8)
    is_superuser = serializers.BooleanField(required=False)

    def get_group_names(self, user):
        return list(user.groups.order_by('name').values_list('name', flat=True))

    def validate(self, attrs):
        if self.instance is None and not attrs.get('password'):
            raise serializers.ValidationError({'password': 'A temporary password of at least 8 characters is required.'})
        if 'is_superuser' in attrs:
            if self.instance is not None:
                raise serializers.ValidationError({'is_superuser': 'Superuser status cannot be changed after account creation.'})
            if attrs['is_superuser'] and not self.context['request'].user.is_superuser:
                raise serializers.ValidationError({'is_superuser': 'Only a superuser can create another superuser.'})
        return attrs

    def create(self, validated_data):
        groups = validated_data.pop('groups', [])
        password = validated_data.pop('password')
        is_superuser = validated_data.pop('is_superuser', False)
        if is_superuser:
            validated_data['is_staff'] = True
        validated_data['is_superuser'] = is_superuser
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        user.groups.set(groups)
        _audit(
            self.context['request'].user,
            'user.created',
            'user',
            user.pk,
            {'username': user.get_username(), 'is_superuser': user.is_superuser},
        )
        return user

    def update(self, instance, validated_data):
        groups = validated_data.pop('groups', None)
        password = validated_data.pop('password', None)
        old_username = instance.get_username()
        if instance.is_superuser and validated_data.get('is_active') is False:
            if User.objects.filter(is_superuser=True, is_active=True).count() <= 1:
                raise serializers.ValidationError({'is_active': 'The last active superuser cannot be deactivated.'})
        user = super().update(instance, validated_data)
        if groups is not None:
            user.groups.set(groups)
        if password:
            user.set_password(password)
            user.save(update_fields=['password'])
            request = self.context['request']
            if request.user.pk == user.pk:
                update_session_auth_hash(request, user)
            else:
                for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
                    if session.get_decoded().get('_auth_user_id') == str(user.pk):
                        session.delete()
        _audit(
            self.context['request'].user,
            'user.updated',
            'user',
            user.pk,
            {
                'username': user.get_username(),
                'previous_username': old_username if old_username != user.get_username() else None,
                'password_reset': bool(password),
                'groups': list(user.groups.values_list('name', flat=True)),
            },
        )
        return user

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'is_active', 'is_staff', 'is_superuser', 'last_login', 'date_joined', 'groups', 'group_names', 'password']
        read_only_fields = ['id', 'last_login', 'date_joined']


class AccessGroupSerializer(serializers.ModelSerializer):
    permission_ids = serializers.PrimaryKeyRelatedField(
        source='permissions',
        queryset=Permission.objects.filter(content_type__app_label='inventory'),
        many=True,
        required=False,
    )
    permission_labels = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()

    def get_permission_labels(self, group):
        return [f'{permission.content_type.model}.{permission.codename}' for permission in group.permissions.select_related('content_type').all()]

    def get_member_count(self, group):
        return group.user_set.count()

    def create(self, validated_data):
        permissions = validated_data.pop('permissions', [])
        group = Group.objects.create(**validated_data)
        group.permissions.set(permissions)
        _audit(self.context['request'].user, 'group.created', 'group', group.pk, {'name': group.name})
        return group

    def update(self, instance, validated_data):
        permissions = validated_data.pop('permissions', None)
        group = super().update(instance, validated_data)
        if permissions is not None:
            group.permissions.set(permissions)
        _audit(self.context['request'].user, 'group.updated', 'group', group.pk, {'name': group.name})
        return group

    class Meta:
        model = Group
        fields = ['id', 'name', 'permission_ids', 'permission_labels', 'member_count']


def _audit(actor, action, target_type, target_id='', details=None):
    SecurityAuditEvent.objects.create(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        details=details or {},
    )
    cache.delete(ACCESS_DASHBOARD_CACHE_KEY)


class AccessUserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.prefetch_related('groups').all().order_by('username')
    serializer_class = AccessUserSerializer
    permission_classes = [IsAdmin]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    search_fields = ['username', 'email', 'first_name', 'last_name']

    @action(detail=True, methods=['post'])
    def force_logout(self, request, pk=None):
        user = self.get_object()
        if user.pk == request.user.pk:
            raise ValidationError({'user': 'Use the sign-out control to end your own session.'})
        removed_sessions = 0
        for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
            if session.get_decoded().get('_auth_user_id') == str(user.pk):
                session.delete()
                removed_sessions += 1
        _audit(request.user, 'user.sessions_revoked', 'user', user.pk, {'username': user.get_username()})
        return Response({'ok': True, 'revoked_sessions': removed_sessions})


class AccessGroupViewSet(viewsets.ModelViewSet):
    queryset = Group.objects.prefetch_related('permissions__content_type', 'user_set').all().order_by('name')
    serializer_class = AccessGroupSerializer
    permission_classes = [IsAdmin]
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def perform_destroy(self, instance):
        if instance.user_set.exists():
            raise ValidationError({'group': 'Remove users from this role before deleting it.'})
        _audit(self.request.user, 'group.deleted', 'group', instance.pk, {'name': instance.name})
        instance.delete()


class AccessDashboardViewSet(viewsets.ViewSet):
    permission_classes = [IsAdmin]

    def list(self, request):
        dashboard = cache.get(ACCESS_DASHBOARD_CACHE_KEY)
        if dashboard is None:
            dashboard = {
                'active_users': User.objects.filter(is_active=True).count(),
                'total_users': User.objects.count(),
                'role_count': Group.objects.count(),
                'disabled_users': User.objects.filter(is_active=False).count(),
                'staff_users': User.objects.filter(is_staff=True).count(),
                'permission_count': Permission.objects.filter(content_type__app_label='inventory').count(),
                'users': AccessUserSerializer(
                    User.objects.prefetch_related('groups').order_by('username'),
                    many=True,
                    context={'request': request},
                ).data,
                'groups': AccessGroupSerializer(
                    Group.objects.prefetch_related('permissions__content_type', 'user_set').order_by('name'),
                    many=True,
                    context={'request': request},
                ).data,
                'permissions': [
                    {
                        'id': permission.id,
                        'codename': permission.codename,
                        'model': permission.content_type.model,
                        'label': str(permission.name),
                        'action': permission.codename.split('_', 1)[0],
                    }
                    for permission in Permission.objects.filter(
                        content_type__app_label='inventory',
                    ).select_related('content_type').order_by('content_type__model', 'codename')
                ],
                'audit_log': SecurityAuditSerializer(
                    SecurityAuditEvent.objects.select_related('actor')[:30],
                    many=True,
                ).data,
            }
            cache.set(
                ACCESS_DASHBOARD_CACHE_KEY,
                dashboard,
                timeout=ACCESS_DASHBOARD_CACHE_TIMEOUT,
            )
        return Response(dashboard)


@method_decorator(csrf_protect, name='dispatch')
class AccessPermissionViewSet(viewsets.ViewSet):
    permission_classes = [IsAdmin]

    def create(self, request):
        group_id = request.data.get('group_id')
        permission_ids = request.data.get('permission_ids', [])
        try:
            group = Group.objects.get(pk=group_id)
        except (Group.DoesNotExist, ValueError, TypeError):
            raise ValidationError({'group_id': 'Select a valid role.'})
        permission_ids = [int(permission_id) for permission_id in permission_ids]
        permissions = Permission.objects.filter(id__in=permission_ids, content_type__app_label='inventory')
        if permissions.count() != len(set(permission_ids)):
            raise ValidationError({'permission_ids': 'One or more permissions are invalid.'})
        group.permissions.set(permissions)
        _audit(request.user, 'group.permissions_updated', 'group', group.pk, {'permission_ids': permission_ids})
        return Response(AccessGroupSerializer(group, context={'request': request}).data)
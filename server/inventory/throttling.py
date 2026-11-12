import hashlib
import time

from rest_framework.settings import api_settings
from rest_framework.throttling import SimpleRateThrottle


class AtomicRateThrottle(SimpleRateThrottle):
    def get_rate(self):
        return api_settings.DEFAULT_THROTTLE_RATES[self.scope]

    def _cache_key(self, ident):
        hashed_ident = hashlib.sha256(ident.encode('utf-8')).hexdigest()
        return self.cache_format % {'scope': self.scope, 'ident': hashed_ident}

    def get_cache_key(self, request, view):
        return self._cache_key(self.get_ident(request))

    def allow_request(self, request, view):
        ident = self.get_cache_key(request, view)
        if ident is None:
            return True
        window = int(time.time() // self.duration)
        self.key = f'{ident}_{window}'
        if self.cache.add(self.key, 1, timeout=self.duration):
            self.count = 1
        else:
            try:
                self.count = self.cache.incr(self.key)
            except ValueError:
                if self.cache.add(self.key, 1, timeout=self.duration):
                    self.count = 1
                else:
                    self.count = self.cache.incr(self.key)
        return self.count <= self.num_requests

    def wait(self):
        return self.duration - (time.time() % self.duration)


class AtomicAnonRateThrottle(AtomicRateThrottle):
    scope = 'anon'


class AtomicUserRateThrottle(AtomicRateThrottle):
    scope = 'user'

    def get_cache_key(self, request, view):
        if request.user.is_authenticated:
            return self._cache_key(f'user:{request.user.pk}')
        return None

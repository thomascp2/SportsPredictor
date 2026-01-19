"""
Simple in-memory cache service
==============================
Reduces API calls and speeds up responses.
"""

import time
from typing import Any, Optional, Dict
from functools import wraps


class SimpleCache:
    """Thread-safe in-memory cache with TTL support."""

    def __init__(self):
        self._cache: Dict[str, tuple] = {}  # key -> (value, expiry_time)

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired."""
        if key not in self._cache:
            return None

        value, expiry = self._cache[key]
        if time.time() > expiry:
            del self._cache[key]
            return None

        return value

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """Set value in cache with TTL (seconds)."""
        expiry = time.time() + ttl
        self._cache[key] = (value, expiry)

    def clear(self, pattern: str = None) -> int:
        """Clear cache entries. If pattern given, only clear matching keys."""
        if pattern is None:
            count = len(self._cache)
            self._cache.clear()
            return count

        keys_to_delete = [k for k in self._cache.keys() if pattern in k]
        for key in keys_to_delete:
            del self._cache[key]
        return len(keys_to_delete)

    def stats(self) -> Dict:
        """Get cache statistics."""
        now = time.time()
        valid = sum(1 for _, expiry in self._cache.values() if expiry > now)
        return {
            'total_entries': len(self._cache),
            'valid_entries': valid,
            'expired_entries': len(self._cache) - valid,
        }


# Global cache instance
cache = SimpleCache()


def cached(ttl: int = 300, key_prefix: str = ''):
    """Decorator for caching function results."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Build cache key from function name and arguments
            cache_key = f"{key_prefix}:{func.__name__}:{str(args)}:{str(sorted(kwargs.items()))}"

            # Try to get from cache
            result = cache.get(cache_key)
            if result is not None:
                return result

            # Call function and cache result
            result = await func(*args, **kwargs)
            cache.set(cache_key, result, ttl)
            return result

        return wrapper
    return decorator

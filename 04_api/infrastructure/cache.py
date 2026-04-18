"""
Cache layer with stale-while-revalidate pattern.
Provides sub-millisecond response times even when DB is under pressure.
"""
from functools import lru_cache
from datetime import datetime, timedelta
from typing import Any, Callable, Optional
import logging
import time
import hashlib
import json

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """
    Simple circuit breaker - fails fast when DB is under pressure.
    Prevents dashboard from timing out during DB contention.
    """
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.is_open = False
    
    def record_success(self):
        """Record successful query - reset circuit"""
        self.failure_count = 0
        self.is_open = False
    
    def record_failure(self):
        """Record failed query - may open circuit"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.is_open = True
            logger.warning(f"Circuit breaker OPENED after {self.failure_count} failures")
    
    def can_execute(self) -> bool:
        """Check if queries are allowed"""
        if not self.is_open:
            return True
        
        # Check if recovery timeout has passed
        if self.last_failure_time:
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.is_open = False
                self.failure_count = 0
                logger.info("Circuit breaker HALF_OPEN - testing recovery")
                return True
        
        return False


class QueryCache:
    """
    In-memory cache with stale-while-revalidate.
    - Fresh data: return immediately
    - Stale but DB slow: return stale, trigger background refresh
    - Expired: try DB, fail gracefully
    """
    
    def __init__(
        self,
        default_ttl: int = 30,
        stale_acceptable_ttl: int = 300,
        max_size: int = 128
    ):
        self.default_ttl = default_ttl
        self.stale_acceptable_ttl = stale_acceptable_ttl
        self.max_size = max_size
        
        # In-memory cache: {key: (data, timestamp)}
        self._cache: dict[str, tuple[Any, float]] = {}
        
        # Circuit breaker for DB calls
        self.circuit_breaker = CircuitBreaker()
    
    def _make_key(self, prefix: str, *args) -> str:
        """Generate cache key from prefix + args"""
        key_data = f"{prefix}:{json.dumps(args, default=str)}"
        return f"cache_{hashlib.sha256(key_data.encode()).hexdigest()[:16]}"
    
    def get(self, key: str) -> Optional[tuple[Any, float]]:
        """Get cached data if exists"""
        return self._cache.get(key)
    
    def set(self, key: str, data: Any, ttl: Optional[int] = None):
        """Cache data with TTL"""
        ttl = ttl or self.default_ttl
        expires_at = time.time() + ttl
        
        # Simple cache eviction if full
        if len(self._cache) >= self.max_size:
            # Remove oldest entry
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]
        
        self._cache[key] = (data, expires_at)
    
    def invalidate(self, pattern: str = ""):
        """Clear cache by pattern"""
        if not pattern:
            self._cache.clear()
        else:
            keys_to_remove = [k for k in self._cache.keys() if pattern in k]
            for k in keys_to_remove:
                del self._cache[k]
    
    def is_fresh(self, key: str) -> bool:
        """Check if cache entry is still fresh"""
        entry = self._cache.get(key)
        if not entry:
            return False
        _, expires_at = entry
        return time.time() < expires_at
    
    def is_stale_acceptable(self, key: str) -> bool:
        """Check if stale data is acceptable (but not expired)"""
        entry = self._cache.get(key)
        if not entry:
            return False
        _, expires_at = entry
        stale_threshold = time.time() + self.stale_acceptable_ttl
        return time.time() < stale_threshold


# Global cache instance - increased TTL to reduce DB load
cache = QueryCache(default_ttl=60, stale_acceptable_ttl=300)


def cached_query(ttl: int = 30, key_prefix: str = "query"):
    """
    Decorator for caching dashboard queries.
    
    Usage:
        @cached_query(ttl=30, key_prefix="dashboard_stats")
        def get_dashboard_stats():
            # expensive DB query here
            return result
    """
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            # Generate cache key
            cache_key = cache._make_key(key_prefix, *args, **kwargs)
            
            # Check circuit breaker first
            if not cache.circuit_breaker.can_execute():
                # Try stale cache before failing
                entry = cache.get(cache_key)
                if entry and cache.is_stale_acceptable(cache_key):
                    logger.info(f"Circuit open - returning stale cache for {key_prefix}")
                    return entry[0]
                raise Exception("Circuit breaker OPEN - database under pressure")
            
            # Check fresh cache
            if cache.is_fresh(cache_key):
                entry = cache.get(cache_key)
                if entry:
                    return entry[0]
            
            # Execute query
            try:
                result = func(*args, **kwargs)
                cache.circuit_breaker.record_success()
                
                # Cache successful result
                cache.set(cache_key, result, ttl)
                return result
                
            except Exception as e:
                cache.circuit_breaker.record_failure()
                
                # Try stale cache on failure
                entry = cache.get(cache_key)
                if entry and cache.is_stale_acceptable(cache_key):
                    logger.warning(f"Query failed, returning stale cache: {e}")
                    return entry[0]
                
                raise
        
        return wrapper


# ========== Quick helpers for manual caching ==========
def get_cached_stats(fetch_func: Callable[[], Any], cache_key: str = "stats") -> Any:
    """
    Simple helper for caching dashboard stats.
    
    Usage:
        stats = get_cached_stats(lambda: db.query(Company).count(), "company_count")
    """
    entry = cache.get(cache_key)
    now = time.time()
    
    # Return fresh cache
    if entry:
        data, expires_at = entry
        if now < expires_at:
            return data
    
    # Fetch fresh data
    try:
        data = fetch_func()
        cache.set(cache_key, data)
        return data
    except Exception as e:
        # Return stale if available
        if entry:
            _, expires_at = entry
            if now < expires_at + cache.stale_acceptable_ttl:
                logger.warning(f"Stats fetch failed, using stale: {e}")
                return entry[0]
        raise
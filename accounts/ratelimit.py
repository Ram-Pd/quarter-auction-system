"""
Simple failed-attempt counter, used to slow down guessing of URNs/passwords.

Two counters per attempt:
  - per account identifier (email or URN): low limit, stops guessing one account
  - per client IP: higher limit, because many honest applicants may share one
    office network address, but it still stops one machine hammering many accounts

Counts are kept in Django's cache. The default cache is in-memory and
per-process, which is fine for development. In production (several
processes) point CACHES at Redis so all processes share the counts.

Usage:
    keys = attempt_keys("activate", request, email)
    if is_blocked(keys): refuse
    ... on failure: record_failure(keys)
    ... on success: reset_identifier(keys)
"""
import hashlib

from django.conf import settings
from django.core.cache import cache


def _client_ip(request):
    # REMOTE_ADDR only. X-Forwarded-For can be faked by the client unless a
    # trusted reverse proxy sets it; revisit when deploying behind one.
    return request.META.get("REMOTE_ADDR", "unknown")


def attempt_keys(action, request, identifier):
    """Return {cache_key: limit} for this action, client IP and identifier."""
    ident = hashlib.sha256(str(identifier).strip().lower().encode()).hexdigest()[:32]
    return {
        f"rl:{action}:id:{ident}": settings.AUTH_RATE_LIMIT_ATTEMPTS,
        f"rl:{action}:ip:{_client_ip(request)}": settings.AUTH_RATE_LIMIT_IP_ATTEMPTS,
    }


def is_blocked(keys):
    return any(cache.get(key, 0) >= limit for key, limit in keys.items())


def record_failure(keys):
    window = settings.AUTH_RATE_LIMIT_WINDOW_SECONDS
    for key in keys:
        if cache.add(key, 1, timeout=window):  # first failure starts the window
            continue
        try:
            cache.incr(key)
        except ValueError:  # expired between add() and incr()
            cache.set(key, 1, timeout=window)


def reset_identifier(keys):
    """After a success, clear the account's counter (the IP counter keeps counting)."""
    cache.delete_many([key for key in keys if ":id:" in key])


def blocked_message():
    minutes = max(1, settings.AUTH_RATE_LIMIT_WINDOW_SECONDS // 60)
    return f"Too many failed attempts. Please wait {minutes} minutes and try again."

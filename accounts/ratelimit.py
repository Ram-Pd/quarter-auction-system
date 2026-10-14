"""
Simple attempt counters, used to slow down password guessing and to limit
how many sign-up codes (OTPs) can be emailed.

Two counters per attempt:
  - per account identifier (email): low limit, stops guessing one account
  - per client IP: higher limit, because many honest applicants may share one
    office network address, but it still stops one machine hammering many accounts

Counts are kept in Django's cache. The default cache is in-memory and
per-process, which is fine for development. In production (several
processes) point CACHES at Redis so all processes share the counts.

Usage (login):
    keys = attempt_keys("login", request, email)
    if is_blocked(keys): refuse
    ... on failure: record_failure(keys)
    ... on success: reset_identifier(keys)

Usage (count every attempt, e.g. OTP emails):
    if not allow("otp_send", request, email, per_id=5, per_ip=20, window=3600): refuse
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


def allow(action, request, identifier, per_id, per_ip, window):
    """
    Count this attempt and say whether it is within the limits (True = go ahead).
    Unlike the login counters, EVERY attempt counts here, successful or not.
    """
    ident = hashlib.sha256(str(identifier).strip().lower().encode()).hexdigest()[:32]
    limits = {f"rl:{action}:id:{ident}": per_id, f"rl:{action}:ip:{_client_ip(request)}": per_ip}
    if any(cache.get(key, 0) >= limit for key, limit in limits.items()):
        return False
    for key in limits:
        if not cache.add(key, 1, timeout=window):
            try:
                cache.incr(key)
            except ValueError:  # expired between add() and incr()
                cache.set(key, 1, timeout=window)
    return True

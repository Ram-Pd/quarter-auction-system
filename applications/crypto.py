"""
Encryption of Aadhaar and PAN numbers ("encrypted at rest").

Two tools, both from the `cryptography` library / Python standard library:

1. encrypt() / decrypt(): Fernet (AES-128 in CBC mode + HMAC-SHA256 tamper check).
   The database only ever holds the encrypted token, e.g. "gAAAAABn...".
   Without FIELD_ENCRYPTION_KEYS (in .env, never in the database or git) a
   stolen database backup does not reveal the numbers.

   FIELD_ENCRYPTION_KEYS is a LIST so keys can be rotated: new data is
   encrypted with the FIRST key, and every key in the list can still decrypt
   (MultiFernet). To rotate: put a new key first, keep the old one after it.

2. blind_index(): a keyed hash (HMAC-SHA256 with IDENTITY_HASH_KEY). The same
   number always gives the same hash, so the database can enforce "one
   application per Aadhaar / PAN" with a unique constraint, without storing
   the number itself. A plain SHA-256 would NOT be safe here: there are only
   about 10^11 valid Aadhaar numbers, so an attacker could hash them all. The
   secret key stops that.

Generate keys with:   python manage.py generate_secret_keys
"""
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _fernet():
    keys = settings.FIELD_ENCRYPTION_KEYS
    if not keys:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEYS is not set in .env "
                                   "(run: python manage.py generate_secret_keys).")
    return MultiFernet([Fernet(key) for key in keys])


def encrypt(text):
    """Plain text -> encrypted token (str). A new random IV every time."""
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token):
    """Encrypted token -> plain text. Raises InvalidToken if the key is wrong or data was altered."""
    return _fernet().decrypt(token.encode()).decode()


def blind_index(kind, value):
    """Keyed hash used only for uniqueness checks, e.g. blind_index("aadhaar", "234567890124")."""
    key = settings.IDENTITY_HASH_KEY
    if not key:
        raise ImproperlyConfigured("IDENTITY_HASH_KEY is not set in .env "
                                   "(run: python manage.py generate_secret_keys).")
    return hmac.new(key.encode(), f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()


__all__ = ["encrypt", "decrypt", "blind_index", "InvalidToken"]

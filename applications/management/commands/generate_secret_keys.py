"""
Print fresh secret keys to paste into .env:

    python manage.py generate_secret_keys

FIELD_ENCRYPTION_KEYS encrypts Aadhaar/PAN; IDENTITY_HASH_KEY makes the
"one application per Aadhaar/PAN" hash. Keep both secret and BACKED UP:
losing FIELD_ENCRYPTION_KEYS means the stored numbers can never be read again.
"""
import secrets

from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Print new FIELD_ENCRYPTION_KEYS and IDENTITY_HASH_KEY values for .env."

    def handle(self, *args, **options):
        self.stdout.write(f"FIELD_ENCRYPTION_KEYS={Fernet.generate_key().decode()}")
        self.stdout.write(f"IDENTITY_HASH_KEY={secrets.token_urlsafe(48)}")

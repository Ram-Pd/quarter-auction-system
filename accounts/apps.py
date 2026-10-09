from django.apps import AppConfig
from django.conf import settings
from django.utils.autoreload import autoreload_started


def watch_env_file(sender, **kwargs):
    """
    Development server: restart automatically when .env changes (e.g. after
    adding the email password), just like it does when a .py file changes.
    Settings are read only at startup, so without this a running server keeps
    the old values.
    """
    sender.extra_files.add(settings.BASE_DIR / ".env")


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        autoreload_started.connect(watch_env_file)

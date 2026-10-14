from django.apps import AppConfig
from django.db.models.signals import post_migrate


class ApplicationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'applications'
    verbose_name = 'Applications and verification'

    def ready(self):
        # After "migrate", make sure the staff groups exist with the right
        # permissions (applications/roles.py). It runs after EVERY app's migrations
        # (not just ours) because the auctions permissions are created after ours.
        # Safe to run any number of times.
        from .roles import setup_groups
        post_migrate.connect(setup_groups, dispatch_uid="applications.setup_groups")

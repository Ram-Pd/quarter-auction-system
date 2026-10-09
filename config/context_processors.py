from django.conf import settings


def reset_link_hours():
    return max(1, settings.PASSWORD_RESET_TIMEOUT // 3600)


def project_settings(request):
    """Values every template may need, read from settings so text never goes stale."""
    return {
        "AUCTION_TITLE": settings.AUCTION_TITLE,
        "RESET_LINK_HOURS": reset_link_hours(),
    }

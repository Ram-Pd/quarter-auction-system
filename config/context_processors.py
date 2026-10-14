from django.conf import settings


def reset_link_hours():
    return max(1, settings.PASSWORD_RESET_TIMEOUT // 3600)


def project_settings(request):
    """
    Values every template may need, read from settings so text never goes stale
    (e.g. the rules page says "5 minutes" because DEFAULT_AUCTION_DURATION_MINUTES is 5).
    """
    return {
        "AUCTION_TITLE": settings.AUCTION_TITLE,
        "RESET_LINK_HOURS": reset_link_hours(),
        "MAX_QUARTERS_PER_APPLICANT": settings.MAX_QUARTERS_PER_APPLICANT,
        "DEFAULT_AUCTION_DURATION_MINUTES": settings.DEFAULT_AUCTION_DURATION_MINUTES,
        "DEFAULT_INCREMENT_PERCENT": settings.DEFAULT_INCREMENT_PERCENT,
        "APPLICATION_CLOSES_HOURS_BEFORE_AUCTION": settings.APPLICATION_CLOSES_HOURS_BEFORE_AUCTION,
        "OTP_VALID_MINUTES": settings.OTP_VALID_MINUTES,
        "QUICK_BID_STEPS": settings.QUICK_BID_STEPS,
    }

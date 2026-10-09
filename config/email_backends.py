import os
from datetime import datetime

from django.core.mail.backends import filebased


class EmlFileBackend(filebased.EmailBackend):
    """
    Development only: like Django's file backend, but names files *.eml so a
    double-click opens them in Outlook / Mail / Thunderbird, attachments included.
    """

    def _get_filename(self):
        if self._fname is None:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            self._fname = os.path.join(self.file_path, f"{timestamp}-{abs(id(self))}.eml")
        return self._fname

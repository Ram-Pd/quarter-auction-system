import os
import sys
from datetime import datetime

from django.core.mail.backends import filebased


class EmlFileBackend(filebased.EmailBackend):
    """
    Development only (used when no SMTP password is set):
      1. saves each email as a *.eml file in sent_emails/ - double-click opens it
         in Outlook / Mail / Thunderbird, attachments (PDFs) included;
      2. ALSO prints the plain-text part to the console, like Django's console
         backend, so a sign-up code (OTP) can be read straight from the terminal.
    """

    def _get_filename(self):
        if self._fname is None:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            self._fname = os.path.join(self.file_path, f"{timestamp}-{abs(id(self))}.eml")
        return self._fname

    def write_message(self, message):
        super().write_message(message)
        attachments = [a[0] if isinstance(a, tuple) else a.get_filename() for a in message.attachments]
        sys.stdout.write(
            "\n" + "-" * 70 + f"\n[email] To: {', '.join(message.to)}\n[email] Subject: {message.subject}\n"
            + (f"[email] Attachments: {', '.join(attachments)}\n" if attachments else "")
            + "\n" + message.body + "\n" + "-" * 70 + "\n")
        sys.stdout.flush()

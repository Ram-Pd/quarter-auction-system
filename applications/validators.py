"""
Format checks and masking for Aadhaar and PAN.

These check the FORMAT only. They cannot tell whether a number really belongs
to the applicant; the Verification Officer checks the original documents.
"""
import re

from django.core.exceptions import ValidationError

# ---------------------------------------------------------------- Aadhaar

# Verhoeff checksum tables. Aadhaar's 12th digit is a Verhoeff check digit, so a
# single mistyped digit or two swapped neighbouring digits is always caught.
_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]
_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def verhoeff_is_valid(number):
    """True if the last digit of `number` (a digit string) is a correct Verhoeff check digit."""
    check = 0
    for i, digit in enumerate(reversed(number)):
        check = _D[check][_P[i % 8][int(digit)]]
    return check == 0


def verhoeff_check_digit(number):
    """The digit to append to `number` to make it Verhoeff-valid (used to make FAKE test numbers)."""
    check = 0
    for i, digit in enumerate(reversed(number)):
        check = _D[check][_P[(i + 1) % 8][int(digit)]]
    return str(_INV[check])


def normalise_aadhaar(value):
    """'2345 6789 0124' or '2345-6789-0124' -> '234567890124'."""
    return re.sub(r"[\s-]", "", value or "")


def validate_aadhaar(value):
    """12 digits, not starting with 0 or 1 (never issued), valid Verhoeff check digit."""
    if not re.fullmatch(r"[2-9]\d{11}", value):
        raise ValidationError("Enter a valid 12-digit Aadhaar number.", code="aadhaar_format")
    if not verhoeff_is_valid(value):
        raise ValidationError("This Aadhaar number is not valid (check digit does not match). "
                              "Please check for a typing mistake.", code="aadhaar_checksum")


# ---------------------------------------------------------------- PAN

# 5 letters, 4 digits, 1 letter, e.g. ABCPE1234F. (The 4th letter is the holder
# type, "P" for an individual; not enforced: placeholder until confirmed.)
PAN_PATTERN = re.compile(r"[A-Z]{5}\d{4}[A-Z]")


def normalise_pan(value):
    return re.sub(r"\s", "", value or "").upper()


def validate_pan(value):
    if not PAN_PATTERN.fullmatch(value):
        raise ValidationError("Enter a valid 10-character PAN, e.g. ABCPE1234F.", code="pan_format")


# ---------------------------------------------------------------- masking

def mask(value, visible=4):
    """Hide all but the last `visible` characters: '234567890124' -> 'XXXXXXXX0124'."""
    value = value or ""
    return "X" * max(0, len(value) - visible) + value[-visible:]


def mask_aadhaar(last4):
    return f"XXXX XXXX {last4}" if last4 else ""


def mask_pan(last4):
    return f"XXXXXX{last4}" if last4 else ""

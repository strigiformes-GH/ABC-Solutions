# input validation


from __future__ import annotations
from email_validator import EmailNotValidError, validate_email


# password requirements to check
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128


def is_valid_email(value: str) -> bool:
    if not value or value != value.strip():
        return False
    try:
        validate_email(value, check_deliverability=False)
        return True
    except EmailNotValidError:
        return False


def is_valid_person_name(value: str, max_length: int = 50) -> bool:
    if not value or value != value.strip() or len(value) > max_length:
        return False
    return value.isprintable() and any(character.isalpha() for character in value)


def is_valid_username(value: str) -> bool:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    return 3 <= len(value) <= 50 and all(character in allowed for character in value)


def is_valid_password(value: str) -> bool:
    return (
        PASSWORD_MIN_LENGTH <= len(value) <= PASSWORD_MAX_LENGTH
        and "\x00" not in value  # reject null character
    )


def is_valid_phone(value: str) -> bool:
    if not value:
        return True  # optional
    allowed = "0123456789 ()-+"
    if len(value) > 50 or any(character not in allowed for character in value):
        return False
    if "+" in value and (not value.startswith("+") or value.count("+") > 1):
        return False
    digit_count = sum(character in "0123456789" for character in value)
    return digit_count >= 6
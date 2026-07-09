import re

_EMAIL = re.compile(r"[^@]+@[^@]+\.[^@]+")


def validate_email(value):
    if not _EMAIL.match(value):
        raise ValueError("invalid email")
    return True

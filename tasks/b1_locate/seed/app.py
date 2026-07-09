from validators import validate_email


def register(email):
    validate_email(email)
    return {"ok": True}

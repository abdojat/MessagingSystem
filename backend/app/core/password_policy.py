import re


PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 256

_UPPERCASE_RE = re.compile(r"[A-Z]")
_LOWERCASE_RE = re.compile(r"[a-z]")
_DIGIT_RE = re.compile(r"[0-9]")
_SPECIAL_RE = re.compile(r"[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]")
_WHITESPACE_RE = re.compile(r"\s")


def password_policy_errors(password: str) -> list[str]:
    """Return stable, user-safe reasons a newly chosen password is rejected."""

    errors: list[str] = []
    if len(password) < PASSWORD_MIN_LENGTH:
        errors.append(f"contain at least {PASSWORD_MIN_LENGTH} characters")
    if len(password) > PASSWORD_MAX_LENGTH:
        errors.append(f"contain at most {PASSWORD_MAX_LENGTH} characters")
    if not _UPPERCASE_RE.search(password):
        errors.append("contain an uppercase letter")
    if not _LOWERCASE_RE.search(password):
        errors.append("contain a lowercase letter")
    if not _DIGIT_RE.search(password):
        errors.append("contain a number")
    if not _SPECIAL_RE.search(password):
        errors.append("contain a special character")
    if _WHITESPACE_RE.search(password):
        errors.append("not contain whitespace")
    return errors


def validate_new_password(password: str) -> str:
    errors = password_policy_errors(password)
    if errors:
        raise ValueError("Password must " + ", ".join(errors) + ".")
    return password

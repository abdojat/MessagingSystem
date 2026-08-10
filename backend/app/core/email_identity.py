"""Canonical email identity handling for account and invite authorization."""


def normalize_email(value: str) -> str:
    """Normalize application emails without provider-specific transformations."""

    return value.strip().lower()

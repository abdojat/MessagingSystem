"""Trusted client-address resolution shared by abuse and resource limits."""

from ipaddress import ip_address, ip_network

from starlette.requests import HTTPConnection

from app.core.config import get_settings


def get_client_ip(connection: HTTPConnection) -> str:
    """Return a bounded client address, trusting forwarding only from configured peers.

    The hardened proxy overwrites ``X-Forwarded-For`` with one validated client
    address. Direct-development mode has no trusted proxy ranges and therefore
    ignores arbitrary forwarding headers.
    """

    connection_client = getattr(connection, "client", None)
    peer = connection_client.host if connection_client else "unknown"
    settings = get_settings()
    try:
        peer_address = ip_address(peer)
    except ValueError:
        return peer[:64]

    trusted = any(peer_address in ip_network(cidr, strict=False) for cidr in settings.trusted_proxy_cidrs)
    if not trusted:
        return peer_address.compressed

    forwarded = connection.headers.get("x-forwarded-for", "").strip()
    # The repository proxy deliberately sends one address, not a client-
    # controlled chain. Refuse ambiguous/malformed values instead of guessing.
    if not forwarded or "," in forwarded or len(forwarded) > 64:
        return peer_address.compressed
    try:
        return ip_address(forwarded).compressed
    except ValueError:
        return peer_address.compressed

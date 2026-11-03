"""Narrow browser form destinations for validated OAuth redirects."""

import ipaddress
import re
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl

from .security.oauth import valid_redirect


def form_redirect_policy(*redirects: str) -> str:
    origins = []
    for redirect in redirects:
        parsed = urlsplit(str(AnyHttpUrl(redirect)))
        if not valid_redirect(redirect):
            raise ValueError("Invalid form redirect")
        host = parsed.hostname or ""
        if not re.fullmatch(r"[A-Za-z0-9.-]+", host):
            try:
                ipaddress.ip_address(host)
            except ValueError:
                raise ValueError("Invalid form redirect host") from None
        origin = parsed.scheme + "://" + parsed.netloc
        if origin not in origins:
            origins.append(origin)
    destinations = "'self'" + ((" " + " ".join(origins)) if origins else "")
    return (
        "default-src 'none'; style-src 'unsafe-inline'; form-action "
        + destinations
        + "; frame-ancestors 'none'; base-uri 'none'"
    )

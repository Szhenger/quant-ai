"""Shared input validators: ticker shape and outbound-URL (SSRF) safety."""
import ipaddress
import re
import socket
from urllib.parse import urlparse

_TICKER_RE = re.compile(r"[A-Z0-9.\-]{1,16}")


class UnresolvableWebhookHostError(ValueError):
    """The webhook host did not resolve. Distinct from a resolved-but-private
    host: resolution failures are often transient (resolver blip, propagation),
    so delivery treats them as retryable while validation still rejects them."""


def normalize_ticker(value: str) -> str:
    """Uppercase/strip a ticker and validate its shape.

    Raises ``ValueError`` on anything that can't be a symbol (spaces, emoji,
    empty). Dots and dashes are legitimate (BRK.B, BF-B).
    """
    ticker = (value or "").upper().strip()
    if not _TICKER_RE.fullmatch(ticker):
        raise ValueError("Ticker may only contain A-Z, 0-9, '.' and '-' (max 16 chars).")
    return ticker


def ensure_public_webhook_url(url: str) -> None:
    """Raise ``ValueError`` unless ``url`` is http(s) to a publicly-routable host.

    First-line SSRF defence for user-supplied webhook targets: the worker POSTs
    these from inside our network, so literal private/loopback/link-local
    addresses — and hostnames that resolve to any non-public address — are
    rejected at validation time. (Post-validation DNS rebinding is out of
    scope; a complete defence needs an egress proxy.)
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Webhook URL must use http or https.")
    host = parsed.hostname
    if not host:
        raise ValueError("Webhook URL has no host.")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            raise UnresolvableWebhookHostError(
                f"Webhook host {host!r} could not be resolved."
            )
        # Strip any IPv6 zone id ("fe80::1%en0") before parsing.
        addresses = [ipaddress.ip_address(str(info[4][0]).split("%")[0]) for info in infos]
    if not addresses or not all(a.is_global for a in addresses):
        raise ValueError(
            "Webhook URL must point at a public address; "
            "private, loopback and link-local hosts are not allowed."
        )

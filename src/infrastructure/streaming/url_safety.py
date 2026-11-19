"""
Outbound Webhook Endpoint Validation — SSRF Baseline Guard.

Used by FHIR R4 Subscription registration (channel.type == "rest-hook") to
reject the most obvious unsafe destinations before this server ever makes
an outbound HTTP request to a caller-supplied URL.

ISO 14971 HAZARD-STREAM-006 (PROPOSED — pending human security/risk-
management sign-off; new hazard introduced by Subscription webhook
delivery, not a resolution of an existing one):
  A FHIR Subscription's channel.endpoint is a URL supplied entirely by
  whoever calls POST /api/v1/fhir/Subscription. Without restriction, this
  server would happily make outbound HTTP requests (carrying FHIR Bundles,
  which may contain clinical data) to ANY address the caller names —
  including the edge appliance's own cloud-metadata endpoint, its
  management interfaces, or other hosts on its internal network
  (Server-Side Request Forgery). This is a data-exfiltration AND an
  internal-network-pivot risk, not merely an availability concern.
  Mitigation implemented here (registration-time only):
    - Scheme must be https:// (http:// is rejected unless explicitly
      opted into — see allow_insecure_http — for local development only).
    - Hostname must be present and must not be a bare IP-address literal
      that falls in a loopback, link-local, private (RFC 1918 / ULA), or
      other non-globally-routable range (via Python's ipaddress module).
    - The literal hostnames "localhost" and "*.local" are rejected.
  NOT mitigated here (residual risk requiring human sign-off before
  production use):
    - DNS rebinding (REDUCED, F-05, 2026-11-19): every delivery re-resolves
      the host and refuses unless all answers are public
      (resolved_addresses_are_public, via the dispatcher's
      _PublicOnlyTransport). The connection pool resolves again right after,
      so a sub-second window remains until the checked IP is pinned.
    - Open redirects (CLOSED): delivery never follows redirects
      (follow_redirects=False, stated explicitly in the dispatcher).
    - Non-canonical IP literals (CLOSED, F-05): decimal / octal / hex / short
      IPv4 forms and IPv4-mapped IPv6 are decoded and judged by is_global.
    - No allow-list mode: a deployment that wants to restrict subscribers
      to specific known-good hosts (the strongest mitigation) is not
      implemented here; this module only provides a deny-list baseline.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

# F-05: ".localhost" (RFC 6761) and public wildcard-DNS services that map any
# name onto an embedded IP (127.0.0.1.nip.io, localtest.me ...) are refused
# by name; everything else is checked on the resolved address at connect time
# (resolved_addresses_are_public + the dispatcher's guarded transport).
_BLOCKED_HOSTNAME_SUFFIXES: tuple[str, ...] = (
    ".local",
    ".localhost",
    ".internal",
    ".nip.io",
    ".sslip.io",
    ".xip.io",
    ".localtest.me",
    ".lvh.me",
)
_BLOCKED_HOSTNAMES: frozenset[str] = frozenset(
    {"localhost", "localtest.me", "lvh.me", "metadata.google.internal"}
)


def _literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """
    The IP a host string denotes as a literal, including the legacy IPv4 forms
    that socket APIs accept but ipaddress does not: decimal (2130706433),
    octal (0177.0.0.1), hex (0x7f.0.0.1) and short (127.1). F-05.
    """
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except (OSError, ValueError):
        return None


def is_public_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Globally routable unicast only; IPv4-mapped IPv6 judged as its IPv4."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def resolved_addresses_are_public(host: str, port: int | None = None) -> bool:
    """
    F-05 connect-time check: every address `host` resolves to must be public.
    Unresolvable hosts fail closed. Used right before each webhook delivery,
    which narrows (does not fully remove) the DNS-rebinding window.
    """
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return False
    addrs = {info[4][0] for info in infos}
    if not addrs:
        return False
    for addr in addrs:
        try:
            ip = ipaddress.ip_address(str(addr).split("%", 1)[0])
        except ValueError:
            return False
        if not is_public_address(ip):
            return False
    return True


class UnsafeWebhookEndpointError(ValueError):
    """Raised when a webhook endpoint fails the SSRF baseline guard."""


def validate_webhook_endpoint(
    url: str,
    *,
    allow_insecure_http: bool = False,
) -> None:
    """
    Raise UnsafeWebhookEndpointError if `url` is not acceptable as a FHIR
    Subscription rest-hook channel.endpoint. Returns None (no exception) if
    the URL passes this registration-time baseline check.

    This is a best-effort deny-list, not a guarantee of safety — see
    HAZARD-STREAM-006 in this module's docstring for what is and is not
    covered.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise UnsafeWebhookEndpointError(
            f"Webhook endpoint scheme must be http or https. Got {parsed.scheme!r}."
        )
    if parsed.scheme == "http" and not allow_insecure_http:
        raise UnsafeWebhookEndpointError(
            "Webhook endpoint must use https:// (HAZARD-STREAM-006: clinical "
            "data would otherwise be sent in plaintext to a caller-supplied "
            "URL). Set allow_insecure_http=True only for local development."
        )

    hostname = parsed.hostname
    if not hostname:
        raise UnsafeWebhookEndpointError(
            f"Webhook endpoint must include a hostname. Got {url!r}."
        )

    if parsed.username is not None or parsed.password is not None:
        raise UnsafeWebhookEndpointError(
            "Webhook endpoint must not embed credentials (user:pass@host); "
            "use channel.header instead."
        )

    lowered = hostname.lower().rstrip(".")
    if lowered in _BLOCKED_HOSTNAMES or lowered.endswith(_BLOCKED_HOSTNAME_SUFFIXES):
        raise UnsafeWebhookEndpointError(
            f"Webhook endpoint hostname {hostname!r} is not permitted "
            "(HAZARD-STREAM-006 SSRF baseline guard)."
        )

    ip = _literal_ip(lowered)
    if ip is None:
        return  # a real hostname: checked again on the resolved address at delivery (F-05)

    if not is_public_address(ip):
        raise UnsafeWebhookEndpointError(
            f"Webhook endpoint IP address {hostname!r} is not a globally "
            "routable address (HAZARD-STREAM-006 SSRF baseline guard)."
        )

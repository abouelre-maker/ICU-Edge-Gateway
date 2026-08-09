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
    - DNS rebinding: a hostname that resolves to a public IP at
      registration time can be repointed to an internal IP by the time
      this server actually connects to deliver a Bundle. Closing this
      gap requires validating the resolved IP at CONNECT time (e.g. a
      custom transport with a connect-time IP check), not just at
      registration time — out of scope for this pass; flagged as an
      explicit residual gap, not silently accepted as solved.
    - Open redirects: this server does not currently disable HTTP
      redirect-following on webhook delivery requests; a validated
      endpoint that redirects to an internal address is not re-validated.
    - No allow-list mode: a deployment that wants to restrict subscribers
      to specific known-good hosts (the strongest mitigation) is not
      implemented here; this module only provides a deny-list baseline.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

_BLOCKED_HOSTNAME_SUFFIXES: tuple[str, ...] = (".local",)
_BLOCKED_HOSTNAMES: frozenset[str] = frozenset({"localhost"})


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

    lowered = hostname.lower()
    if lowered in _BLOCKED_HOSTNAMES or lowered.endswith(_BLOCKED_HOSTNAME_SUFFIXES):
        raise UnsafeWebhookEndpointError(
            f"Webhook endpoint hostname {hostname!r} is not permitted "
            "(HAZARD-STREAM-006 SSRF baseline guard)."
        )

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return  # not an IP literal -- a real hostname, allowed (see residual DNS-rebinding gap)

    if (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        raise UnsafeWebhookEndpointError(
            f"Webhook endpoint IP address {hostname!r} is not a globally "
            "routable address (HAZARD-STREAM-006 SSRF baseline guard)."
        )

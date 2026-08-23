"""
Unit Tests — infrastructure.streaming.url_safety (HAZARD-STREAM-006 SSRF baseline guard).

Verifies the registration-time deny-list used before this gateway ever
makes an outbound HTTP request to a caller-supplied FHIR Subscription
webhook endpoint.
"""

from __future__ import annotations

import pytest
from infrastructure.streaming.url_safety import (
    UnsafeWebhookEndpointError,
    validate_webhook_endpoint,
)


class TestAcceptedEndpoints:
    def test_https_public_hostname_is_accepted(self) -> None:
        validate_webhook_endpoint("https://ehr.example.org/fhir/subscriptions")

    def test_https_public_hostname_with_port_is_accepted(self) -> None:
        validate_webhook_endpoint("https://ehr.example.org:8443/hook")

    def test_http_is_accepted_when_explicitly_allowed(self) -> None:
        validate_webhook_endpoint(
            "http://dev.example.org/hook", allow_insecure_http=True
        )


class TestRejectedScheme:
    def test_rejects_non_http_scheme(self) -> None:
        with pytest.raises(
            UnsafeWebhookEndpointError, match="scheme must be http or https"
        ):
            validate_webhook_endpoint("ftp://example.org/hook")

    def test_rejects_http_by_default(self) -> None:
        with pytest.raises(UnsafeWebhookEndpointError, match="must use https"):
            validate_webhook_endpoint("http://ehr.example.org/hook")


class TestRejectedHostname:
    def test_rejects_missing_hostname(self) -> None:
        with pytest.raises(UnsafeWebhookEndpointError, match="must include a hostname"):
            validate_webhook_endpoint("https:///hook")

    def test_rejects_localhost(self) -> None:
        with pytest.raises(UnsafeWebhookEndpointError, match="not permitted"):
            validate_webhook_endpoint(
                "https://localhost/hook", allow_insecure_http=True
            )

    def test_rejects_dot_local_suffix(self) -> None:
        with pytest.raises(UnsafeWebhookEndpointError, match="not permitted"):
            validate_webhook_endpoint("https://printer.local/hook")

    def test_hostname_check_is_case_insensitive(self) -> None:
        with pytest.raises(UnsafeWebhookEndpointError, match="not permitted"):
            validate_webhook_endpoint("https://LOCALHOST/hook")


class TestRejectedIpLiterals:
    @pytest.mark.parametrize(
        "url",
        [
            "https://127.0.0.1/hook",  # loopback
            "https://169.254.169.254/hook",  # link-local / cloud metadata
            "https://10.0.0.5/hook",  # RFC 1918 private
            "https://172.16.0.5/hook",  # RFC 1918 private
            "https://192.168.1.5/hook",  # RFC 1918 private
            "https://0.0.0.0/hook",  # unspecified
            "https://[::1]/hook",  # IPv6 loopback
        ],
    )
    def test_rejects_non_globally_routable_ip_literal(self, url: str) -> None:
        with pytest.raises(UnsafeWebhookEndpointError, match="not a globally routable"):
            validate_webhook_endpoint(url)

    def test_accepts_globally_routable_ip_literal(self) -> None:
        validate_webhook_endpoint("https://8.8.8.8/hook")

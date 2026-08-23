"""
Integration Tests — infrastructure.provisioning.enrollment_client.

Uses httpx.MockTransport, same pattern as
test_fhir_subscription_api.py::TestSubscriptionEndToEndDelivery -- no real
network call leaves the test process. Backoff is configured to
near-zero seconds in every test so retry scenarios run fast without
mocking asyncio.sleep.

Covers (per Phase 5 Section B requirement 4): enrollment handshake happy
path, expired token, reused token, mid-handshake network interruption, and
revoked certificate (reattest()).
"""

from __future__ import annotations

import json

import httpx
import pytest
from infrastructure.provisioning.enrollment_client import (
    DeviceEnrollmentClient,
    EnrollmentNetworkError,
    ReattestationResult,
    TokenRejectedError,
)

_BOOTSTRAP_URL = "https://control-plane.example.org/provisioning"
_CSR_PEM = b"-----BEGIN CERTIFICATE REQUEST-----\nfake\n-----END CERTIFICATE REQUEST-----\n"


def _client(handler) -> DeviceEnrollmentClient:
    return DeviceEnrollmentClient(
        _BOOTSTRAP_URL,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_attempts=3,
        base_backoff_seconds=0.001,
        max_backoff_seconds=0.005,
    )


@pytest.mark.integration
class TestEnrollHappyPath:
    async def test_returns_issued_credentials_on_201(self) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(
                201,
                json={
                    "certificate_pem": "-----BEGIN CERTIFICATE-----\ncert\n-----END CERTIFICATE-----\n",
                    "ca_chain_pem": "-----BEGIN CERTIFICATE-----\nca\n-----END CERTIFICATE-----\n",
                },
            )

        client = _client(handler)
        credentials = await client.enroll("valid-token", _CSR_PEM)

        assert credentials.certificate_pem.startswith(b"-----BEGIN CERTIFICATE-----")
        assert credentials.ca_chain_pem.startswith(b"-----BEGIN CERTIFICATE-----")
        assert len(calls) == 1
        assert calls[0].url.path.endswith("/enroll")
        assert calls[0].headers["Authorization"] == "Bearer valid-token"

    async def test_never_logs_or_transmits_token_in_body(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                201,
                json={"certificate_pem": "cert", "ca_chain_pem": "ca"},
            )

        client = _client(handler)
        await client.enroll("super-secret-token", _CSR_PEM)

        # Token travels ONLY in the Authorization header, never in the
        # request body (which is more likely to be logged/cached).
        assert "super-secret-token" not in json.dumps(captured["body"])


@pytest.mark.integration
class TestEnrollTokenRejected:
    async def test_expired_token_raises_immediately_no_retry(self) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(401, json={"detail": "token expired"})

        client = _client(handler)
        with pytest.raises(TokenRejectedError) as exc_info:
            await client.enroll("expired-token", _CSR_PEM)

        assert exc_info.value.status_code == 401
        assert exc_info.value.reason == "invalid_or_unauthenticated"
        assert len(calls) == 1  # NOT retried

    async def test_reused_token_raises_immediately_no_retry(self) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(409, json={"detail": "token already redeemed"})

        client = _client(handler)
        with pytest.raises(TokenRejectedError) as exc_info:
            await client.enroll("already-used-token", _CSR_PEM)

        assert exc_info.value.status_code == 409
        assert exc_info.value.reason == "already_used"
        assert len(calls) == 1  # NOT retried -- retrying a replay is itself abuse


@pytest.mark.integration
class TestEnrollNetworkInterruption:
    async def test_recovers_after_transient_failures_within_max_attempts(self) -> None:
        attempts = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise httpx.ConnectError("connection reset mid-handshake")
            return httpx.Response(
                201, json={"certificate_pem": "cert", "ca_chain_pem": "ca"}
            )

        client = _client(handler)  # max_attempts=3
        credentials = await client.enroll("valid-token", _CSR_PEM)

        assert credentials.certificate_pem == b"cert"
        assert attempts["count"] == 3

    async def test_exhausts_bounded_attempts_and_raises(self) -> None:
        attempts = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            raise httpx.ConnectError("permanently unreachable")

        client = _client(handler)  # max_attempts=3
        with pytest.raises(EnrollmentNetworkError):
            await client.enroll("valid-token", _CSR_PEM)

        # Rate-limited (HAZARD-STREAM-010): bounded, not infinite, retries.
        assert attempts["count"] == 3

    async def test_max_attempts_of_one_makes_a_single_call(self) -> None:
        attempts = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            raise httpx.ConnectError("down")

        client = DeviceEnrollmentClient(
            _BOOTSTRAP_URL,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            max_attempts=1,
            base_backoff_seconds=0.001,
        )
        with pytest.raises(EnrollmentNetworkError):
            await client.enroll("valid-token", _CSR_PEM)

        assert attempts["count"] == 1


@pytest.mark.integration
class TestReattestRevocation:
    async def test_200_means_not_revoked(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        client = _client(lambda r: httpx.Response(201))  # unused enroll handler
        mtls_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        result = await client.reattest(mtls_client)

        assert result == ReattestationResult(revoked=False, status_code=200)

    async def test_401_means_revoked(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401)

        client = _client(lambda r: httpx.Response(201))
        mtls_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        result = await client.reattest(mtls_client)

        assert result.revoked is True
        assert result.status_code == 401

    async def test_403_means_revoked(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403)

        client = _client(lambda r: httpx.Response(201))
        mtls_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        result = await client.reattest(mtls_client)

        assert result.revoked is True

    async def test_network_failure_during_reattest_is_not_treated_as_revocation(
        self,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("WAN outage")

        client = _client(lambda r: httpx.Response(201))
        mtls_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        # Raises (distinct signal), rather than returning revoked=True --
        # a WAN outage must not masquerade as a revocation decision.
        with pytest.raises(EnrollmentNetworkError):
            await client.reattest(mtls_client)

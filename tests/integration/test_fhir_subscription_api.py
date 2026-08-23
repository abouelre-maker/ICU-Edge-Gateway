"""
Integration Tests — POST/GET/DELETE /api/v1/fhir/Subscription.

Uses starlette.testclient.TestClient (sync), not the async `client` fixture:
TestClient actually drives the ASGI lifespan protocol (confirmed against
test_main_mllp_lifespan.py's finding that httpx.ASGITransport does not
here), and app.state.subscription_registry is only populated once lifespan
has run. The 503-if-registry-missing guard in api/v1/fhir_subscription.py's
_registry() is covered separately, using the (lifespan-inert) `client`
fixture on purpose, to prove the fallback path itself works.

The end-to-end delivery tests swap httpx.MockTransport onto the already-
running dispatcher's http client after startup, so no real network call
leaves the test process.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest
from httpx import AsyncClient
from main import create_app
from starlette.testclient import TestClient

# HAZARD-STREAM-009: every route in api/v1/fhir_subscription.py requires
# this pre-shared secret. Set for every test in this module so existing
# behavior (create/read/list/delete) is exercised past the auth gate --
# the auth gate itself is covered separately below by
# TestRegistrationAuthentication, which deliberately omits/breaks it.
_TEST_SECRET = "test-only-registration-secret-do-not-use-in-prod"
_AUTH_HEADERS = {"Authorization": f"Bearer {_TEST_SECRET}"}


@pytest.fixture(autouse=True)
def _registration_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FHIR_SUBSCRIPTION_REGISTRATION_SECRET", _TEST_SECRET)


_VALID_PAYLOAD = {
    "resourceType": "Subscription",
    "criteria": "Bundle",
    "reason": "Dashboard integration test",
    "channel": {
        "type": "rest-hook",
        "endpoint": "https://ehr.example.org/fhir/subscriptions/hook",
        "payload": "application/fhir+json",
    },
}

FULL_ORU = (
    "MSH|^~\\&|GENERIC_MONITOR|ICU_UNIT|EHR|HOSPITAL|20240115100000"
    "||ORU^R01|MSG001|P|2.5.1\r"
    "PID|1||PT-SUB-001^^^HOSP^MR||DOE^JOHN||19800101|M\r"
    "OBR|1||ORDER-001|||||20240115100000\r"
    "OBX|1|NM|8867-4^Heart rate^LN||72|/min|60-100||||F|||20240115100000\r"
    "OBX|2|NM|59408-5^SpO2^LN||98|%|95-100||||F|||20240115100000\r"
    "OBX|3|NM|9279-1^Respiratory rate^LN||16|/min|12-20||||F|||20240115100000\r"
    "OBX|4|NM|8480-6^Systolic BP^LN||120|mmHg|90-140||||F|||20240115100000\r"
    "OBX|5|NM|8310-5^Temperature^LN||37.0|Cel|36.1-38.0||||F|||20240115100000\r"
    "OBX|6|NM|57834-7^Supplemental O2^LN||0||||||F|||20240115100000\r"
)


def _wait_until(predicate, timeout: float = 2.0, interval: float = 0.02) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(f"Condition not met within {timeout}s")


@pytest.mark.integration
class TestRegistryMissingFallback:
    """
    The `client` fixture (httpx.ASGITransport) does not drive ASGI lifespan
    here, so app.state.subscription_registry is never set -- exactly the
    "bare app" scenario _registry()'s getattr guard exists for.
    """

    async def test_returns_503_when_registry_not_initialized(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/fhir/Subscription", json=_VALID_PAYLOAD, headers=_AUTH_HEADERS
        )
        assert response.status_code == 503


@pytest.mark.integration
class TestCreateSubscriptionEndpoint:
    def test_returns_201_and_fhir_shape(self) -> None:
        with TestClient(create_app()) as client:
            response = client.post(
                "/api/v1/fhir/Subscription", json=_VALID_PAYLOAD, headers=_AUTH_HEADERS
            )
            assert response.status_code == 201
            body = response.json()
            assert body["resourceType"] == "Subscription"
            assert body["status"] == "active"  # registry.create() activates immediately
            assert body["criteria"] == "Bundle"
            assert body["id"]

    def test_invalid_criteria_returns_422(self) -> None:
        with TestClient(create_app()) as client:
            payload = {**_VALID_PAYLOAD, "criteria": "Observation?code=1975-2"}
            response = client.post(
                "/api/v1/fhir/Subscription", json=payload, headers=_AUTH_HEADERS
            )
            assert response.status_code == 422
            assert "Unsupported Subscription.criteria" in response.json()["detail"]

    def test_unsafe_endpoint_returns_422(self) -> None:
        with TestClient(create_app()) as client:
            payload = {
                **_VALID_PAYLOAD,
                "channel": {
                    **_VALID_PAYLOAD["channel"],
                    "endpoint": "https://127.0.0.1/hook",
                },
            }
            response = client.post(
                "/api/v1/fhir/Subscription", json=payload, headers=_AUTH_HEADERS
            )
            assert response.status_code == 422

    def test_unimplemented_channel_type_returns_422(self) -> None:
        with TestClient(create_app()) as client:
            payload = {
                **_VALID_PAYLOAD,
                "channel": {**_VALID_PAYLOAD["channel"], "type": "websocket"},
            }
            response = client.post(
                "/api/v1/fhir/Subscription", json=payload, headers=_AUTH_HEADERS
            )
            assert response.status_code == 422
            assert "NOT IMPLEMENTED" in response.json()["detail"]


@pytest.mark.integration
class TestReadAndListSubscriptionEndpoints:
    def test_read_after_create_round_trips(self) -> None:
        with TestClient(create_app()) as client:
            created = client.post(
                "/api/v1/fhir/Subscription", json=_VALID_PAYLOAD, headers=_AUTH_HEADERS
            ).json()
            response = client.get(
                f"/api/v1/fhir/Subscription/{created['id']}", headers=_AUTH_HEADERS
            )
            assert response.status_code == 200
            assert response.json()["id"] == created["id"]

    def test_read_unknown_id_returns_404(self) -> None:
        with TestClient(create_app()) as client:
            response = client.get(
                "/api/v1/fhir/Subscription/does-not-exist", headers=_AUTH_HEADERS
            )
            assert response.status_code == 404

    def test_list_returns_searchset_bundle(self) -> None:
        with TestClient(create_app()) as client:
            client.post(
                "/api/v1/fhir/Subscription", json=_VALID_PAYLOAD, headers=_AUTH_HEADERS
            )
            client.post(
                "/api/v1/fhir/Subscription", json=_VALID_PAYLOAD, headers=_AUTH_HEADERS
            )

            response = client.get("/api/v1/fhir/Subscription", headers=_AUTH_HEADERS)
            assert response.status_code == 200
            body = response.json()
            assert body["resourceType"] == "Bundle"
            assert body["type"] == "searchset"
            assert body["total"] == 2
            assert len(body["entry"]) == 2


@pytest.mark.integration
class TestDeleteSubscriptionEndpoint:
    def test_delete_existing_returns_204(self) -> None:
        with TestClient(create_app()) as client:
            created = client.post(
                "/api/v1/fhir/Subscription", json=_VALID_PAYLOAD, headers=_AUTH_HEADERS
            ).json()
            response = client.delete(
                f"/api/v1/fhir/Subscription/{created['id']}", headers=_AUTH_HEADERS
            )
            assert response.status_code == 204

            follow_up = client.get(
                f"/api/v1/fhir/Subscription/{created['id']}", headers=_AUTH_HEADERS
            )
            assert follow_up.status_code == 404

    def test_delete_unknown_id_returns_404(self) -> None:
        with TestClient(create_app()) as client:
            response = client.delete(
                "/api/v1/fhir/Subscription/does-not-exist", headers=_AUTH_HEADERS
            )
            assert response.status_code == 404


@pytest.mark.integration
class TestRegistrationAuthentication:
    """
    HAZARD-STREAM-009: POST/GET/DELETE /api/v1/fhir/Subscription accept and
    disclose caller-supplied webhook credentials (channel.header) and must
    not be reachable without a correct pre-shared registration secret.
    These tests deliberately do NOT rely on the module-level
    `_registration_secret` autouse fixture's header being attached, so they
    exercise the actual rejection path rather than assuming it works.
    """

    def test_unauthenticated_create_is_rejected(self) -> None:
        with TestClient(create_app()) as client:
            response = client.post("/api/v1/fhir/Subscription", json=_VALID_PAYLOAD)
            assert response.status_code == 401
            assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_wrong_secret_create_is_rejected(self) -> None:
        with TestClient(create_app()) as client:
            response = client.post(
                "/api/v1/fhir/Subscription",
                json=_VALID_PAYLOAD,
                headers={"Authorization": "Bearer not-the-right-secret"},
            )
            assert response.status_code == 401

    def test_malformed_authorization_scheme_is_rejected(self) -> None:
        with TestClient(create_app()) as client:
            response = client.post(
                "/api/v1/fhir/Subscription",
                json=_VALID_PAYLOAD,
                headers={"Authorization": f"Basic {_TEST_SECRET}"},
            )
            assert response.status_code == 401

    def test_unauthenticated_read_is_rejected(self) -> None:
        with TestClient(create_app()) as client:
            created = client.post(
                "/api/v1/fhir/Subscription", json=_VALID_PAYLOAD, headers=_AUTH_HEADERS
            ).json()
            response = client.get(f"/api/v1/fhir/Subscription/{created['id']}")
            assert response.status_code == 401

    def test_unauthenticated_list_is_rejected(self) -> None:
        with TestClient(create_app()) as client:
            response = client.get("/api/v1/fhir/Subscription")
            assert response.status_code == 401

    def test_unauthenticated_delete_is_rejected(self) -> None:
        with TestClient(create_app()) as client:
            created = client.post(
                "/api/v1/fhir/Subscription", json=_VALID_PAYLOAD, headers=_AUTH_HEADERS
            ).json()
            response = client.delete(f"/api/v1/fhir/Subscription/{created['id']}")
            assert response.status_code == 401
            # And it genuinely was NOT deleted -- reachable with the secret.
            follow_up = client.get(
                f"/api/v1/fhir/Subscription/{created['id']}", headers=_AUTH_HEADERS
            )
            assert follow_up.status_code == 200

    def test_missing_server_side_secret_returns_503_not_401(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Overrides this module's autouse fixture: proves the fail-closed
        # ops-misconfiguration path (503) is distinct from a caller-side
        # auth failure (401), even when the caller presents *some* token.
        monkeypatch.delenv("FHIR_SUBSCRIPTION_REGISTRATION_SECRET", raising=False)
        with TestClient(create_app()) as client:
            response = client.post(
                "/api/v1/fhir/Subscription", json=_VALID_PAYLOAD, headers=_AUTH_HEADERS
            )
            assert response.status_code == 503


@pytest.mark.integration
class TestSubscriptionEndToEndDelivery:
    """
    Full path: create a Subscription via the REST API -> POST HL7 to
    /api/v1/ingest -> the dispatcher wired by main.py's lifespan delivers
    the resulting Bundle to the subscriber. httpx.MockTransport is swapped
    onto the already-running dispatcher's http client so no real network
    call happens. Delivery is fire-and-forget (see subscription_dispatcher.
    py), so assertions poll with a timeout rather than assuming it has
    already happened the instant the ingest POST returns.
    """

    def test_matching_bundle_is_delivered_to_subscriber_endpoint(self) -> None:
        received: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            received.append(json.loads(request.content))
            return httpx.Response(200)

        with TestClient(create_app()) as client:
            client.app.state.subscription_dispatcher._client = httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            )

            create_resp = client.post(
                "/api/v1/fhir/Subscription",
                json={
                    **_VALID_PAYLOAD,
                    "criteria": "Bundle?patient=Patient/PT-SUB-001",
                },
                headers=_AUTH_HEADERS,
            )
            assert create_resp.status_code == 201

            ingest_resp = client.post(
                "/api/v1/ingest",
                content=FULL_ORU,
                headers={"Content-Type": "text/plain"},
            )
            assert ingest_resp.status_code == 200

            _wait_until(lambda: len(received) == 1)

        assert received[0]["resourceType"] == "Bundle"

    def test_non_matching_patient_is_not_delivered(self) -> None:
        received: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            received.append({})
            return httpx.Response(200)

        with TestClient(create_app()) as client:
            client.app.state.subscription_dispatcher._client = httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            )

            client.post(
                "/api/v1/fhir/Subscription",
                json={
                    **_VALID_PAYLOAD,
                    "criteria": "Bundle?patient=Patient/SOME-OTHER-PATIENT",
                },
                headers=_AUTH_HEADERS,
            )
            client.post(
                "/api/v1/ingest",
                content=FULL_ORU,
                headers={"Content-Type": "text/plain"},
            )
            # Nothing to poll for by design -- give the (absent) delivery a
            # window to wrongly fire before asserting it didn't.
            time.sleep(0.2)

        assert received == []

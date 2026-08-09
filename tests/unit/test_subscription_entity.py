"""
Unit Tests — infrastructure.fhir.subscription (entity, validation, FHIR shape).

Covers create_subscription_from_fhir_request()'s validation (the fail-fast
guard against HAZARD-STREAM-007 -- accepted-but-never-matching criteria)
and Subscription.to_fhir_dict()'s FHIR R4 resource shape.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from infrastructure.fhir.subscription import (
    SubscriptionChannelType,
    SubscriptionStatus,
    create_subscription_from_fhir_request,
    parse_patient_filter,
)

_VALID_PAYLOAD = {
    "resourceType": "Subscription",
    "criteria": "Bundle",
    "reason": "Test subscription",
    "channel": {
        "type": "rest-hook",
        "endpoint": "https://ehr.example.org/fhir/subscriptions/hook",
        "payload": "application/fhir+json",
    },
}


class TestParsePatientFilter:
    def test_bare_bundle_matches_all(self) -> None:
        assert parse_patient_filter("Bundle") is None

    def test_patient_scoped_criteria_extracts_id(self) -> None:
        assert parse_patient_filter("Bundle?patient=Patient/PT-001") == "PT-001"

    def test_unsupported_criteria_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported Subscription.criteria"):
            parse_patient_filter("Observation?code=1975-2")

    def test_unsupported_criteria_extra_params_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported Subscription.criteria"):
            parse_patient_filter("Bundle?patient=Patient/PT-001&status=final")


class TestCreateSubscriptionValidResource:
    def test_creates_with_requested_status_and_new_id(self) -> None:
        sub = create_subscription_from_fhir_request(_VALID_PAYLOAD)
        assert sub.status is SubscriptionStatus.REQUESTED
        assert sub.criteria == "Bundle"
        assert sub.channel.type is SubscriptionChannelType.REST_HOOK
        assert sub.channel.endpoint == _VALID_PAYLOAD["channel"]["endpoint"]
        assert sub.id  # non-empty, generated

    def test_patient_scoped_criteria_is_accepted(self) -> None:
        payload = {**_VALID_PAYLOAD, "criteria": "Bundle?patient=Patient/PT-042"}
        sub = create_subscription_from_fhir_request(payload)
        assert sub.criteria == "Bundle?patient=Patient/PT-042"

    def test_headers_are_preserved(self) -> None:
        payload = {
            **_VALID_PAYLOAD,
            "channel": {
                **_VALID_PAYLOAD["channel"],
                "header": ["Authorization: Bearer abc123"],
            },
        }
        sub = create_subscription_from_fhir_request(payload)
        assert sub.channel.headers == ("Authorization: Bearer abc123",)

    def test_valid_future_end_is_accepted(self) -> None:
        future = (datetime.now(tz=timezone.utc) + timedelta(days=1)).isoformat()
        payload = {**_VALID_PAYLOAD, "end": future}
        sub = create_subscription_from_fhir_request(payload)
        assert sub.end is not None


class TestCreateSubscriptionRejections:
    def test_rejects_wrong_resource_type(self) -> None:
        payload = {**_VALID_PAYLOAD, "resourceType": "Patient"}
        with pytest.raises(ValueError, match="resourceType must be 'Subscription'"):
            create_subscription_from_fhir_request(payload)

    def test_rejects_missing_criteria(self) -> None:
        payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "criteria"}
        with pytest.raises(ValueError, match="criteria is required"):
            create_subscription_from_fhir_request(payload)

    def test_rejects_unsupported_criteria(self) -> None:
        payload = {**_VALID_PAYLOAD, "criteria": "Observation?code=1975-2"}
        with pytest.raises(ValueError, match="Unsupported Subscription.criteria"):
            create_subscription_from_fhir_request(payload)

    def test_rejects_missing_channel(self) -> None:
        payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "channel"}
        with pytest.raises(ValueError, match="channel is required"):
            create_subscription_from_fhir_request(payload)

    def test_rejects_unknown_channel_type(self) -> None:
        payload = {
            **_VALID_PAYLOAD,
            "channel": {**_VALID_PAYLOAD["channel"], "type": "carrier-pigeon"},
        }
        with pytest.raises(ValueError, match="Unsupported Subscription.channel.type"):
            create_subscription_from_fhir_request(payload)

    @pytest.mark.parametrize("channel_type", ["websocket", "email", "sms", "message"])
    def test_rejects_valid_fhir_but_unimplemented_channel_types(
        self, channel_type: str
    ) -> None:
        payload = {
            **_VALID_PAYLOAD,
            "channel": {**_VALID_PAYLOAD["channel"], "type": channel_type},
        }
        with pytest.raises(ValueError, match="NOT IMPLEMENTED"):
            create_subscription_from_fhir_request(payload)

    def test_rejects_missing_endpoint(self) -> None:
        payload = {
            **_VALID_PAYLOAD,
            "channel": {
                k: v for k, v in _VALID_PAYLOAD["channel"].items() if k != "endpoint"
            },
        }
        with pytest.raises(ValueError, match="channel.endpoint is required"):
            create_subscription_from_fhir_request(payload)

    def test_rejects_unsafe_endpoint(self) -> None:
        payload = {
            **_VALID_PAYLOAD,
            "channel": {
                **_VALID_PAYLOAD["channel"],
                "endpoint": "https://127.0.0.1/hook",
            },
        }
        with pytest.raises(ValueError, match="not a globally routable"):
            create_subscription_from_fhir_request(payload)

    def test_rejects_unsupported_payload_mime_type(self) -> None:
        payload = {
            **_VALID_PAYLOAD,
            "channel": {**_VALID_PAYLOAD["channel"], "payload": "application/xml"},
        }
        with pytest.raises(ValueError, match="is not supported"):
            create_subscription_from_fhir_request(payload)

    def test_rejects_naive_end_datetime(self) -> None:
        payload = {**_VALID_PAYLOAD, "end": "2030-01-01T00:00:00"}
        with pytest.raises(ValueError, match="must be timezone-aware"):
            create_subscription_from_fhir_request(payload)

    def test_rejects_malformed_end_datetime(self) -> None:
        payload = {**_VALID_PAYLOAD, "end": "not-a-date"}
        with pytest.raises(ValueError, match="not a valid ISO 8601 datetime"):
            create_subscription_from_fhir_request(payload)


class TestToFhirDict:
    def test_basic_shape(self) -> None:
        sub = create_subscription_from_fhir_request(_VALID_PAYLOAD)
        resource = sub.to_fhir_dict()
        assert resource["resourceType"] == "Subscription"
        assert resource["id"] == sub.id
        assert resource["status"] == "requested"
        assert resource["criteria"] == "Bundle"
        assert resource["channel"]["type"] == "rest-hook"
        assert resource["channel"]["endpoint"] == sub.channel.endpoint
        assert resource["channel"]["payload"] == "application/fhir+json"
        assert resource["channel"]["header"] == []

    def test_last_error_becomes_extension(self) -> None:
        sub = create_subscription_from_fhir_request(_VALID_PAYLOAD)
        sub.last_error = "HTTP 503 from subscriber endpoint"
        resource = sub.to_fhir_dict()
        assert (
            resource["extension"][0]["valueString"]
            == "HTTP 503 from subscriber endpoint"
        )

    def test_no_extension_when_no_error(self) -> None:
        sub = create_subscription_from_fhir_request(_VALID_PAYLOAD)
        assert "extension" not in sub.to_fhir_dict()

    def test_end_is_serialized_as_z_suffixed_iso8601(self) -> None:
        payload = {**_VALID_PAYLOAD, "end": "2030-06-15T12:00:00+00:00"}
        sub = create_subscription_from_fhir_request(payload)
        assert sub.to_fhir_dict()["end"] == "2030-06-15T12:00:00Z"

"""
FHIR R4 Subscription — Entity, Validation, and (De)Serialization.

Phase 5 Section A: lets a downstream system (EHR, monitoring platform)
register interest in Bundle updates via the standard FHIR R4 Subscription
resource shape instead of a bespoke per-customer integration. Delivery
(rest-hook POST) lives in infrastructure/streaming/subscription_dispatcher.py;
matching/storage lives in infrastructure/streaming/subscription_registry.py.
This module owns only the resource's shape and validation rules.

FHIR R4 Reference: http://hl7.org/fhir/R4/subscription.html

CONFORMANCE SCOPE — read before assuming standard FHIR search support:
  FHIR R4 Subscription.criteria is, in general, an arbitrary FHIR search
  expression (e.g. "Observation?code=http://loinc.org|1975-2"). This
  gateway does NOT implement a general FHIR search engine. Only two
  criteria forms are accepted:
    "Bundle"                          -> matches every Bundle produced
    "Bundle?patient=Patient/{id}"     -> matches only Bundles for that
                                          patient (matched via
                                          fhir_bundle_utils.extract_patient_id)
  Any other criteria string is REJECTED at registration time (HTTP 422)
  rather than silently accepted and never matched — an accepted-but-
  never-firing subscription would be a silent data-loss hazard for the
  subscriber (see HAZARD-STREAM-007 in subscription_registry.py).
  Only channel.type == "rest-hook" is supported; "websocket", "email",
  "sms", and "message" channel types defined by the FHIR R4 spec are
  rejected at registration time as NOT IMPLEMENTED, not silently ignored.

ISO 14971 HAZARD-FHIR-004 (PROPOSED — pending human sign-off; new hazard,
not a resolution of an existing one): a Subscription resource returned to
a caller (e.g. after creation) must not leak another subscriber's
`channel.header` values (which typically carry authentication secrets,
e.g. "Authorization: Bearer <token>") if this endpoint is ever extended to
a multi-tenant list operation. Mitigation implemented here: to_fhir_dict()
always includes header keys — callers configuring their own subscription
need to see the auth header they set — but this module exposes no
"list all subscriptions across tenants" concept; the registry's list()
method returning every header to every caller is accepted as an
in-scope, single-tenant-appliance assumption. Flagged for human review if
this is ever deployed multi-tenant.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Final

from infrastructure.streaming.url_safety import validate_webhook_endpoint

_SUBSCRIPTION_PROFILE: Final = "http://hl7.org/fhir/StructureDefinition/Subscription"
_DEFAULT_PAYLOAD_MIME_TYPE: Final = "application/fhir+json"

_CRITERIA_PATIENT_RE: Final = re.compile(
    r"^Bundle\?patient=Patient/(?P<patient_id>[^&]+)$"
)


class SubscriptionStatus(str, Enum):
    """FHIR R4 Subscription.status. All four states are supported."""

    REQUESTED = "requested"
    ACTIVE = "active"
    ERROR = "error"
    OFF = "off"


class SubscriptionChannelType(str, Enum):
    """
    FHIR R4 Subscription.channel.type. Only REST_HOOK is implemented —
    see this module's docstring "CONFORMANCE SCOPE" section. The other
    three are declared so validation can name-and-reject them explicitly
    rather than the caller getting an opaque enum error.
    """

    REST_HOOK = "rest-hook"
    WEBSOCKET = "websocket"
    EMAIL = "email"
    SMS = "sms"
    MESSAGE = "message"


@dataclass(frozen=True)
class SubscriptionChannel:
    type: SubscriptionChannelType
    endpoint: str
    payload_mime_type: str = _DEFAULT_PAYLOAD_MIME_TYPE
    headers: tuple[
        str, ...
    ] = ()  # "Header-Name: value" strings, FHIR R4 channel.header


@dataclass
class Subscription:
    """
    A registered FHIR R4 Subscription. Mutable (status/error tracking
    change over the subscription's lifetime); the registry owns the
    single authoritative instance per id.
    """

    id: str
    criteria: str
    channel: SubscriptionChannel
    reason: str = ""
    status: SubscriptionStatus = SubscriptionStatus.REQUESTED
    end: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    consecutive_delivery_errors: int = 0
    last_error: str | None = None

    def to_fhir_dict(self) -> dict[str, Any]:
        resource: dict[str, Any] = {
            "resourceType": "Subscription",
            "id": self.id,
            "meta": {"profile": [_SUBSCRIPTION_PROFILE]},
            "status": self.status.value,
            "reason": self.reason,
            "criteria": self.criteria,
            "channel": {
                "type": self.channel.type.value,
                "endpoint": self.channel.endpoint,
                "payload": self.channel.payload_mime_type,
                "header": list(self.channel.headers),
            },
        }
        if self.end is not None:
            resource["end"] = self.end.isoformat().replace("+00:00", "Z")
        if self.last_error is not None:
            # FHIR R4 base Subscription has no standard top-level error-text
            # field (that arrives in R5) -- exposed as a custom extension,
            # consistent with this codebase's existing extension pattern
            # (see infrastructure/fhir/news2_builder.py's risk-level extension).
            resource["extension"] = [
                {
                    "url": "https://samd.icu-edge/fhir/extensions/subscription-last-error",
                    "valueString": self.last_error,
                }
            ]
        return resource


def parse_patient_filter(criteria: str) -> str | None:
    """
    Extract the patient_id filter from a supported criteria string.

    Returns None for "Bundle" (match-all). Raises ValueError for any
    criteria string outside the supported subset — see this module's
    "CONFORMANCE SCOPE" docstring.
    """
    if criteria == "Bundle":
        return None
    match = _CRITERIA_PATIENT_RE.match(criteria)
    if match:
        return match.group("patient_id")
    raise ValueError(
        f"Unsupported Subscription.criteria: {criteria!r}. This gateway only "
        "supports 'Bundle' (all patients) or 'Bundle?patient=Patient/{id}' "
        "(a single patient) -- not general FHIR search expressions. See "
        "infrastructure/fhir/subscription.py's CONFORMANCE SCOPE docstring."
    )


def create_subscription_from_fhir_request(
    payload: dict[str, Any],
    *,
    allow_insecure_http: bool = False,
) -> Subscription:
    """
    Validate a caller-supplied FHIR Subscription creation request and build
    a Subscription. Raises ValueError (-> HTTP 422 via main.py's global
    handler) for anything outside this gateway's supported subset.
    """
    if payload.get("resourceType") != "Subscription":
        raise ValueError(
            f"resourceType must be 'Subscription'. Got {payload.get('resourceType')!r}."
        )

    criteria = payload.get("criteria")
    if not isinstance(criteria, str) or not criteria:
        raise ValueError(
            "Subscription.criteria is required and must be a non-empty string."
        )
    parse_patient_filter(criteria)  # raises ValueError if unsupported -- fail fast

    channel_payload = payload.get("channel")
    if not isinstance(channel_payload, dict):
        raise ValueError("Subscription.channel is required.")

    channel_type_raw = channel_payload.get("type")
    try:
        channel_type = SubscriptionChannelType(channel_type_raw)
    except ValueError as exc:
        raise ValueError(
            f"Unsupported Subscription.channel.type: {channel_type_raw!r}. "
            f"Valid FHIR R4 values: {[t.value for t in SubscriptionChannelType]}."
        ) from exc
    if channel_type is not SubscriptionChannelType.REST_HOOK:
        raise ValueError(
            f"Subscription.channel.type={channel_type.value!r} is a valid FHIR R4 "
            "value but is NOT IMPLEMENTED by this gateway -- only 'rest-hook' is "
            "supported. See infrastructure/fhir/subscription.py CONFORMANCE SCOPE."
        )

    endpoint = channel_payload.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint:
        raise ValueError(
            "Subscription.channel.endpoint is required for type 'rest-hook'."
        )
    validate_webhook_endpoint(endpoint, allow_insecure_http=allow_insecure_http)

    headers_raw = channel_payload.get("header", [])
    if not isinstance(headers_raw, list) or not all(
        isinstance(h, str) for h in headers_raw
    ):
        raise ValueError(
            "Subscription.channel.header, if present, must be a list of strings."
        )

    payload_mime = channel_payload.get("payload") or _DEFAULT_PAYLOAD_MIME_TYPE
    if payload_mime != _DEFAULT_PAYLOAD_MIME_TYPE:
        raise ValueError(
            f"Subscription.channel.payload={payload_mime!r} is not supported -- "
            f"only {_DEFAULT_PAYLOAD_MIME_TYPE!r} is delivered by this gateway."
        )

    end: datetime | None = None
    end_raw = payload.get("end")
    if end_raw is not None:
        try:
            end = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                f"Subscription.end is not a valid ISO 8601 datetime: {end_raw!r}."
            ) from exc
        if end.tzinfo is None:
            raise ValueError(
                "Subscription.end must be timezone-aware (ISO 14971 HAZARD-TIME-001 "
                "convention applied consistently across this codebase)."
            )

    return Subscription(
        id=str(uuid.uuid4()),
        criteria=criteria,
        channel=SubscriptionChannel(
            type=channel_type,
            endpoint=endpoint,
            payload_mime_type=payload_mime,
            headers=tuple(headers_raw),
        ),
        reason=str(payload.get("reason") or ""),
        status=SubscriptionStatus.REQUESTED,
        end=end,
    )

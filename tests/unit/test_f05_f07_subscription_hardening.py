"""
F-05 (SSRF), F-06 (limits, secret comparison) and F-07 (header injection,
credential disclosure, header logging) for FHIR Subscriptions.
"""

from __future__ import annotations

import asyncio
import ipaddress
from typing import Any

import httpx
import pytest
from infrastructure.fhir.subscription import create_subscription_from_fhir_request
from infrastructure.streaming import url_safety
from infrastructure.streaming.subscription_dispatcher import (
    SubscriptionDispatcher,
    _parse_header_lines,
    _PublicOnlyTransport,
)
from infrastructure.streaming.subscription_registry import SubscriptionRegistry
from infrastructure.streaming.url_safety import (
    UnsafeWebhookEndpointError,
    is_public_address,
    resolved_addresses_are_public,
    validate_webhook_endpoint,
)

_PAYLOAD: dict[str, Any] = {
    "resourceType": "Subscription",
    "status": "requested",
    "reason": "test",
    "criteria": "Bundle",
    "channel": {"type": "rest-hook", "endpoint": "https://ehr.example.org/hook"},
}


def _payload(**channel: Any) -> dict[str, Any]:
    return {**_PAYLOAD, "channel": {**_PAYLOAD["channel"], **channel}}


# ── F-05: registration-time bypass forms ─────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://2130706433/hook",  # decimal 127.0.0.1
        "https://0177.0.0.1/hook",  # octal
        "https://0x7f000001/hook",  # hex
        "https://127.1/hook",  # short form
        "https://[::ffff:127.0.0.1]/hook",  # IPv4-mapped IPv6
        "https://[::1]/hook",
        "https://100.64.0.1/hook",  # carrier-grade NAT, not global
        "https://169.254.169.254/latest/meta-data",  # cloud metadata
        "https://127.0.0.1.nip.io/hook",  # wildcard DNS onto loopback
        "https://app.localtest.me/hook",
        "https://localhost./hook",  # trailing dot
        "https://api.localhost/hook",
        "https://metadata.google.internal/hook",
        "https://user:pass@ehr.example.org/hook",  # embedded credentials
    ],
)
def test_bypass_forms_are_refused(url: str) -> None:
    with pytest.raises(UnsafeWebhookEndpointError):
        validate_webhook_endpoint(url)


@pytest.mark.parametrize("url", ["https://ehr.example.org/hook", "https://8.8.8.8/hook"])
def test_public_endpoints_still_pass(url: str) -> None:
    validate_webhook_endpoint(url)


def test_ipv4_mapped_public_is_public() -> None:
    assert is_public_address(ipaddress.ip_address("::ffff:8.8.8.8"))
    assert not is_public_address(ipaddress.ip_address("::ffff:10.0.0.1"))


# ── F-05: connect-time check ──────────────────────────────────────────────────


def _fake_resolver(addrs: list[str]) -> Any:
    def resolve(host: str, port: Any, **_: Any) -> list[Any]:  # noqa: ARG001
        return [(0, 0, 0, "", (a, 443)) for a in addrs]

    return resolve


def test_name_resolving_to_private_is_not_public(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(url_safety.socket, "getaddrinfo", _fake_resolver(["10.1.2.3"]))
    assert not resolved_addresses_are_public("ehr.example.org", 443)


def test_any_private_answer_fails_the_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        url_safety.socket, "getaddrinfo", _fake_resolver(["93.184.216.34", "127.0.0.1"])
    )
    assert not resolved_addresses_are_public("ehr.example.org", 443)


def test_all_public_answers_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(url_safety.socket, "getaddrinfo", _fake_resolver(["93.184.216.34"]))
    assert resolved_addresses_are_public("ehr.example.org", 443)


def test_unresolvable_host_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: Any, **__: Any) -> Any:
        raise OSError("no such host")

    monkeypatch.setattr(url_safety.socket, "getaddrinfo", boom)
    assert not resolved_addresses_are_public("nope.invalid", 443)


async def test_guarded_transport_refuses_internal_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(url_safety.socket, "getaddrinfo", _fake_resolver(["192.168.1.10"]))
    async with httpx.AsyncClient(transport=_PublicOnlyTransport()) as client:
        with pytest.raises(httpx.ConnectError, match="non-public"):
            await client.post("https://ehr.example.org/hook", content=b"{}")


def test_default_dispatcher_client_does_not_follow_redirects() -> None:
    dispatcher = SubscriptionDispatcher(registry=SubscriptionRegistry())
    assert dispatcher._client.follow_redirects is False


# ── F-06: limits ──────────────────────────────────────────────────────────────


def test_registry_is_bounded() -> None:
    registry = SubscriptionRegistry(max_subscriptions=2)
    for _ in range(2):
        registry.create(create_subscription_from_fhir_request(_PAYLOAD))
    with pytest.raises(ValueError, match="limit"):
        registry.create(create_subscription_from_fhir_request(_PAYLOAD))
    assert len(registry.list_all()) == 2


async def test_deliveries_in_flight_are_bounded() -> None:
    gate = asyncio.Event()

    async def slow(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        await gate.wait()
        return httpx.Response(200)

    registry = SubscriptionRegistry()
    for _ in range(3):
        registry.create(create_subscription_from_fhir_request(_PAYLOAD))
    dispatcher = SubscriptionDispatcher(
        registry=registry,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(slow)),
        max_in_flight=2,
    )
    bundle = {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {
                    "resourceType": "Observation",
                    "code": {"coding": [{"system": "http://loinc.org", "code": "1104-8"}]},
                }
            }
        ],
    }
    matched = await dispatcher.dispatch(bundle)
    assert matched == 3
    assert len(dispatcher._in_flight) == 2
    failures = [s for s in registry.list_all() if s.last_error and "too many" in s.last_error]
    assert len(failures) == 1
    gate.set()
    await asyncio.sleep(0.05)
    assert not dispatcher._in_flight
    await dispatcher.aclose()


# ── F-07: header injection, disclosure, logging ──────────────────────────────


@pytest.mark.parametrize(
    "line",
    [
        "Authorization: Bearer x\r\nX-Injected: 1",
        "X-Bad: a\nb",
        "X-Nul: a\x00b",
        "No colon here",
        "Bad Name: value",
        "X-Long: " + "a" * 2000,
    ],
)
def test_unsafe_header_lines_are_refused(line: str) -> None:
    with pytest.raises(ValueError):
        create_subscription_from_fhir_request(_payload(header=[line]))


def test_too_many_header_lines_are_refused() -> None:
    with pytest.raises(ValueError, match="at most"):
        create_subscription_from_fhir_request(
            _payload(header=[f"X-H{i}: v" for i in range(11)])
        )


def test_responses_do_not_disclose_header_values() -> None:
    sub = create_subscription_from_fhir_request(
        _payload(header=["Authorization: Bearer s3cr3t-token", "X-Tenant: hosp-a"])
    )
    shown = sub.to_fhir_dict()["channel"]["header"]
    assert shown == ["Authorization: ***", "X-Tenant: ***"]
    assert "s3cr3t" not in str(sub.to_fhir_dict())
    # The real value is still used for delivery.
    assert sub.channel.headers[0] == "Authorization: Bearer s3cr3t-token"


def test_malformed_stored_header_is_skipped_without_logging_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parsed = _parse_header_lines(("garbage-with-secret-ABC123", "X-Ok: 1"))
    assert parsed == {"X-Ok": "1"}
    assert "ABC123" not in capsys.readouterr().out

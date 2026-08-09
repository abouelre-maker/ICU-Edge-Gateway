"""
FHIR R4 Subscription REST API — POST/GET/DELETE /api/v1/fhir/Subscription.

Phase 5 Section A. Lets a downstream system register interest in Bundle
updates by topic (see infrastructure/fhir/subscription.py's CONFORMANCE
SCOPE docstring for exactly which criteria forms are supported) instead of
requiring a bespoke per-customer integration -- create a Subscription once,
receive an HTTP POST to your own endpoint every time a matching Bundle is
produced (infrastructure/streaming/subscription_dispatcher.py).

IEC 62304 §5.3: Single responsibility — HTTP CRUD adaptation layer only.
All matching/storage logic is in SubscriptionRegistry; all delivery logic
is in SubscriptionDispatcher. ISO 14971 hazards for this feature
(HAZARD-STREAM-006/007/008) are documented in those modules, not repeated
here.
FDA CDS Non-Device Exemption: every delivered Bundle carries the same
X-CDS-Advisory-Only marker as the REST ingestion responses (added in
subscription_dispatcher.py's delivery headers) — Subscription delivery is
a transport, not a new clinical output.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from infrastructure.fhir.subscription import create_subscription_from_fhir_request
from infrastructure.streaming.subscription_registry import SubscriptionRegistry

_log: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["FHIR Subscription"])


def _registry(request: Request) -> SubscriptionRegistry:
    registry = getattr(request.app.state, "subscription_registry", None)
    if registry is None:
        # Only reachable if a test builds a bare app without main.py's
        # lifespan — production always has this set (see main.py).
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Subscription registry is not initialized on this app instance.",
        )
    return registry


@router.post(
    "/fhir/Subscription",
    status_code=status.HTTP_201_CREATED,
    summary="Create a FHIR R4 Subscription",
    description=(
        "Register a rest-hook Subscription. On creation this gateway POSTs "
        "the matching Bundle to `channel.endpoint` every time a Bundle is "
        "produced whose `criteria` matches. See infrastructure/fhir/"
        "subscription.py for the supported (non-general-FHIR-search) "
        "criteria subset."
    ),
    responses={
        201: {
            "description": "FHIR R4 Subscription (application/fhir+json), status=active."
        },
        422: {"description": "Unsupported criteria, channel type, or unsafe endpoint."},
    },
)
async def create_subscription(request: Request) -> JSONResponse:
    body = await request.json()
    log = _log.bind(criteria=body.get("criteria") if isinstance(body, dict) else None)
    log.info("api.fhir_subscription.create.start")

    # ValueError -> caught by main.py's global handler -> HTTP 422, same
    # convention as every other domain-validation failure in this codebase.
    subscription = create_subscription_from_fhir_request(body)
    _registry(request).create(subscription)

    log.info("api.fhir_subscription.create.complete", subscription_id=subscription.id)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=subscription.to_fhir_dict(),
        media_type="application/fhir+json",
    )


@router.get(
    "/fhir/Subscription/{subscription_id}",
    summary="Read a FHIR R4 Subscription",
    responses={
        200: {"description": "FHIR R4 Subscription (application/fhir+json)."},
        404: {"description": "No Subscription with this id."},
    },
)
async def read_subscription(subscription_id: str, request: Request) -> JSONResponse:
    subscription = _registry(request).get(subscription_id)
    if subscription is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No Subscription with id {subscription_id!r}.",
        )
    return JSONResponse(
        content=subscription.to_fhir_dict(), media_type="application/fhir+json"
    )


@router.get(
    "/fhir/Subscription",
    summary="Search FHIR R4 Subscriptions",
    description=(
        "Returns every registered Subscription as a FHIR R4 searchset Bundle. "
        "No FHIR search parameters are implemented in this pass -- this always "
        "returns the full set (single-tenant appliance assumption; see "
        "infrastructure/fhir/subscription.py HAZARD-FHIR-004)."
    ),
)
async def list_subscriptions(request: Request) -> JSONResponse:
    subscriptions = _registry(request).list_all()
    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(subscriptions),
        "entry": [{"resource": sub.to_fhir_dict()} for sub in subscriptions],
    }
    return JSONResponse(content=bundle, media_type="application/fhir+json")


@router.delete(
    "/fhir/Subscription/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel a FHIR R4 Subscription",
    responses={
        204: {"description": "Subscription deleted."},
        404: {"description": "No Subscription with this id."},
    },
)
async def delete_subscription(subscription_id: str, request: Request) -> None:
    deleted = _registry(request).delete(subscription_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No Subscription with id {subscription_id!r}.",
        )

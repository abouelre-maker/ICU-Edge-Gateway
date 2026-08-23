"""
POST /reattest — Lambda handler, behind an ALB target group in mTLS
"Passthrough" mode (see ../main.tf's header note for why Passthrough, not
Verify).

Because Passthrough mode does NOT verify the client certificate at the
load balancer, THIS HANDLER is where that verification actually happens:
  1. Require the forwarded client-cert header to be present at all (no
     cert presented -> 401, matching enrollment_client.py's expectation
     that reattest() is called against an mTLS-configured client).
  2. Verify the presented cert chains to modules/ca's root (fetched from
     step-ca's own /roots.pem, cached per Lambda execution environment)
     -- NOT trusted just because ALB forwarded it; ALB forwarding a cert
     says nothing about whether it's valid.
  3. Extract the device's common_name from the verified cert.
  4. Check the revocation table for that device -- 403 if revoked
     (matching enrollment_client.py's reattest(), which treats
     401/403 as revoked=True), 200 otherwise.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.request

import boto3
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.x509.verification import PolicyBuilder, Store

_dynamodb = boto3.resource("dynamodb")
_REVOCATIONS_TABLE = _dynamodb.Table(os.environ["REVOCATIONS_TABLE"])
_STEP_CA_ENDPOINT = os.environ["STEP_CA_ENDPOINT"]

_ca_root_cache: x509.Certificate | None = None


def _load_ca_root() -> x509.Certificate:
    """Cached per warm Lambda execution environment -- one fetch per cold
    start, not per request. If step-ca ever rotates its root, a cold
    start (new execution environment) picks up the change; this is not
    instantaneous propagation, a known tradeoff of this simple caching
    approach, acceptable given root rotation is a rare, planned event."""
    global _ca_root_cache
    if _ca_root_cache is None:
        with urllib.request.urlopen(
            f"https://{_STEP_CA_ENDPOINT}/roots.pem", timeout=10
        ) as response:
            _ca_root_cache = x509.load_pem_x509_certificate(response.read())
    return _ca_root_cache


def _verify_and_extract_common_name(cert_pem: bytes) -> str | None:
    """Returns the verified cert's CN, or None if the cert does not chain
    to modules/ca's root (untrusted -- do NOT extract an identity from an
    unverified certificate, that would defeat the entire point of mTLS
    here)."""
    leaf = x509.load_pem_x509_certificate(cert_pem)
    root = _load_ca_root()

    store = Store([root])
    builder = PolicyBuilder().store(store)
    verifier = builder.build_client_verifier()
    try:
        verifier.verify(leaf, [])
    except Exception:  # noqa: BLE001 -- any verification failure means untrusted, full stop
        return None

    return str(leaf.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value)


def handler(event: dict, _context: object) -> dict:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    forwarded_cert_b64 = headers.get("x-amzn-mtls-clientcert-leaf")
    if not forwarded_cert_b64:
        return _response(401, {"detail": "no device identity presented"})

    try:
        cert_pem = base64.b64decode(forwarded_cert_b64)
    except Exception:  # noqa: BLE001
        return _response(401, {"detail": "malformed client certificate"})

    common_name = _verify_and_extract_common_name(cert_pem)
    if common_name is None:
        return _response(401, {"detail": "client certificate does not chain to a trusted CA"})

    revocation = _REVOCATIONS_TABLE.get_item(
        Key={"device_common_name": common_name}
    ).get("Item")
    if revocation is not None and revocation.get("revoked", False):
        return _response(403, {"detail": "device revoked"})

    return _response(200, {"status": "ok"})


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }

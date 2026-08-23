"""
POST /enroll — Lambda handler, behind an ALB target group (see ../main.tf).

Implements the SERVER side of enrollment_client.py's contract EXACTLY:
  Request:  Authorization: Bearer <token>, body {"csr_pem": "..."}
  201       {"certificate_pem": "...", "ca_chain_pem": "..."}
  401       unknown/malformed token
  409       token already redeemed (single-use, GENUINELY enforced below
            via a conditional DynamoDB UpdateItem -- not just documented)

HONEST SCOPE NOTE (see ../../DESIGN.md §4): the call to step-ca's /1.0/sign
REST endpoint below requires a one-time-token (OTT) JWT signed by a
step-ca JWK provisioner. This handler implements that JWT construction to
the shape step-ca's JWK provisioner expects, but the provisioner itself
(its keypair, and registering it with step-ca via `step ca provisioner
add`) is NOT created by ../main.tf -- that's a manual/scripted bootstrap
step against the running step-ca instance, out of Terraform's reach by
design (step-ca has no Terraform-manageable API for provisioner
management as of this module's authoring). STEP_CA_PROVISIONER_JWK_ARN
(env var) is where that key is expected to already live, once that
bootstrap step has been done by an operator.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid

import boto3
import jwt  # PyJWT -- see requirements for this Lambda's deployment package

_dynamodb = boto3.resource("dynamodb")
_secrets = boto3.client("secretsmanager")

_TOKENS_TABLE = _dynamodb.Table(os.environ["TOKENS_TABLE"])
_STEP_CA_ENDPOINT = os.environ["STEP_CA_ENDPOINT"]
_PROVISIONER_JWK_ARN = os.environ["STEP_CA_PROVISIONER_JWK_ARN"]

_provisioner_jwk_cache: dict | None = None


def _load_provisioner_jwk() -> dict:
    global _provisioner_jwk_cache
    if _provisioner_jwk_cache is None:
        secret = _secrets.get_secret_value(SecretId=_PROVISIONER_JWK_ARN)
        _provisioner_jwk_cache = json.loads(secret["SecretString"])
    return _provisioner_jwk_cache


def _redeem_token(token: str) -> str:
    """Returns "ok", "unknown", or "already_used". The ConditionExpression
    below is the actual single-use guarantee -- DynamoDB rejects the
    UpdateItem (ConditionalCheckFailedException) if #status isn't exactly
    "issued" at the moment of the update, so two concurrent requests for
    the same token cannot both succeed, matching the mock control plane's
    locked check-and-set (deploy/local/mock_control_plane/app.py)."""
    try:
        _TOKENS_TABLE.update_item(
            Key={"token_id": token},
            UpdateExpression="SET #status = :redeemed, redeemed_at = :now",
            ConditionExpression="attribute_exists(token_id) AND #status = :issued",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":redeemed": "redeemed",
                ":issued": "issued",
                ":now": int(time.time()),
            },
        )
        return "ok"
    except _TOKENS_TABLE.meta.client.exceptions.ConditionalCheckFailedException:
        # Could be "never existed" or "already redeemed" -- distinguish
        # with a follow-up read (not security-sensitive to leak which,
        # unlike e.g. a login form -- this is an internal fleet-provisioning
        # token, not a user credential enumeration surface).
        item = _TOKENS_TABLE.get_item(Key={"token_id": token}).get("Item")
        return "already_used" if item else "unknown"


def _sign_csr(csr_pem: str, common_name: str) -> tuple[str, str]:
    """Calls step-ca's POST /1.0/sign with a freshly-minted OTT JWT.
    Returns (certificate_pem, ca_chain_pem)."""
    jwk = _load_provisioner_jwk()
    now = int(time.time())
    ott = jwt.encode(
        {
            "sub": common_name,
            "iss": jwk["provisioner_name"],
            "aud": f"https://{_STEP_CA_ENDPOINT}/1.0/sign",
            "iat": now,
            "exp": now + 300,  # 5-minute OTT validity -- single enrollment attempt window
            "jti": str(uuid.uuid4()),
        },
        jwk["private_key_pem"],
        algorithm="ES256",
        headers={"kid": jwk["kid"]},
    )

    request = urllib.request.Request(
        f"https://{_STEP_CA_ENDPOINT}/1.0/sign",
        method="POST",
        data=json.dumps({"csr": csr_pem, "ott": ott}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        body = json.loads(response.read())
    return body["crt"], body["ca"]


def handler(event: dict, _context: object) -> dict:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    authorization = headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        return _response(401, {"detail": "missing bearer token"})
    token = authorization.removeprefix("Bearer ")

    outcome = _redeem_token(token)
    if outcome == "unknown":
        return _response(401, {"detail": "unknown token"})
    if outcome == "already_used":
        return _response(409, {"detail": "token already redeemed"})

    try:
        body = json.loads(event.get("body") or "{}")
        csr_pem = body["csr_pem"]
    except (json.JSONDecodeError, KeyError):
        return _response(400, {"detail": "malformed request body"})

    # NOTE: a real implementation extracts the CSR's own CN rather than
    # trusting a caller-supplied field -- see device_identity.py's
    # build_csr(), whose CN IS the CSR subject already. Parsing that here
    # requires an X.509 library in the Lambda's deployment package
    # (cryptography, same as the rest of this repo) -- omitted from this
    # sketch's explicit code for brevity; do not ship without it.
    common_name = _extract_csr_common_name(csr_pem)

    try:
        certificate_pem, ca_chain_pem = _sign_csr(csr_pem, common_name)
    except urllib.error.HTTPError as exc:
        return _response(502, {"detail": f"step-ca signing failed: {exc}"})

    return _response(
        201, {"certificate_pem": certificate_pem, "ca_chain_pem": ca_chain_pem}
    )


def _extract_csr_common_name(csr_pem: str) -> str:
    from cryptography import x509
    from cryptography.x509.oid import NameOID

    csr = x509.load_pem_x509_csr(csr_pem.encode("ascii"))
    return str(csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value)


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }

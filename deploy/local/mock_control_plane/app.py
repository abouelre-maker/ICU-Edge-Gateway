"""
Mock Control Plane — Local Development Only.

Implements the SERVER side of the protocol infrastructure/provisioning/
enrollment_client.py already codifies as a contract on the device side.
This is NOT the production control plane -- there is no production
control-plane implementation in this repository (that's a separate
service; see infra/terraform/modules/provisioning-api for real
infrastructure that would host it). This module exists ONLY so
docker-compose can exercise the full device<->control-plane handshake
locally without a real cloud deployment.

Contract implemented (matches enrollment_client.py exactly -- do not
diverge without updating both sides):
  POST /enroll
    Headers: Authorization: Bearer <enrollment_token>
    Body:    {"csr_pem": "<PEM-encoded PKCS#10 CSR>"}
    201 {"certificate_pem": "...", "ca_chain_pem": "..."} on success.
    401 if the token is unknown/malformed. 403 reserved (not used by this
    mock -- no tenant-scoping concept here). 409 if the token has ALREADY
    been redeemed -- genuinely enforced via the in-memory token state
    store below (a ConditionExpression-style check-and-set), not just
    documented as single-use.
  POST /reattest
    mTLS-authenticated in a real deployment (the reverse proxy/ingress
    terminates mTLS and forwards the verified client cert's identity --
    not reimplemented here; this mock instead trusts an
    X-Mock-Device-Id header set by a local reverse proxy or test client,
    clearly named to make it obvious this is a LOCAL-DEV SHORTCUT, not a
    real authentication mechanism).
    200 if the device is not revoked. 401/403 if it has been revoked
    (see POST /revoke/{device_id}, a mock-only admin endpoint for
    exercising the revocation path locally).

SECURITY: this mock has NO real security. It accepts any token that
happens to be in its in-memory _VALID_TOKENS set (seeded from an env var
at startup), keeps all state in-process (lost on restart), and its
"mTLS" is a plain header. Never deploy this outside a local docker-compose
network.
"""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Lock, Thread

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel

app = FastAPI(title="ICU Edge Gateway — Mock Control Plane (local dev only)")


# ── Mock CA -- loaded from files generate_certs.py writes BEFORE this app
# is started (see Dockerfile's CMD) -- NOT generated here, so the CA
# signing device certs (below) and the CA that signed THIS server's own
# HTTPS leaf cert are the same one. See generate_certs.py's docstring for
# why that matters for CA-pinning to actually work end-to-end locally.
_CERT_DIR = os.getenv("MOCK_CP_CERT_DIR", "/tmp")
_CA_KEY_PATH = os.path.join(_CERT_DIR, "ca.key")
_CA_CERT_PATH = os.path.join(_CERT_DIR, "ca.crt")


def _load_ca() -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    try:
        with open(_CA_KEY_PATH, "rb") as fh:
            key = serialization.load_pem_private_key(fh.read(), password=None)
        with open(_CA_CERT_PATH, "rb") as fh:
            cert = x509.load_pem_x509_certificate(fh.read())
    except OSError as exc:
        raise RuntimeError(
            f"Mock CA files not found at {_CA_KEY_PATH!r}/{_CA_CERT_PATH!r} -- "
            "run generate_certs.py BEFORE starting uvicorn (see Dockerfile's CMD)."
        ) from exc
    assert isinstance(key, ec.EllipticCurvePrivateKey)  # noqa: S101 -- dev-only mock
    return key, cert


_CA_KEY, _CA_CERT = _load_ca()
_CA_CERT_PEM = _CA_CERT.public_bytes(serialization.Encoding.PEM)


def _issue_device_certificate(csr_pem: str, common_name: str) -> bytes:
    """Sign a short-lived (24h -- deliberately short, matching the
    'short-lived certificates' half of HAZARD-STREAM-011's mitigation
    design) leaf certificate off the CSR's public key."""
    csr = x509.load_pem_x509_csr(csr_pem.encode("ascii"))
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(_CA_CERT.subject)
        .public_key(csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(hours=24))
        .sign(_CA_KEY, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM)


# ── Token state store (single-use enforcement, genuinely enforced) ──────────
@dataclass
class _TokenRecord:
    redeemed: bool = False
    issued_device_common_name: str | None = None


class _TokenStore:
    """
    In-memory, process-local. A real control plane would back this with a
    real datastore and a conditional/atomic write (e.g. DynamoDB
    ConditionExpression on a status attribute -- see infra/terraform's
    provisioning-api module) so single-use enforcement survives multiple
    API instances; this mock uses a plain Lock since it's a single
    process, but the CHECK-AND-SET semantics are the same shape a real
    implementation must have.
    """

    def __init__(self, valid_tokens: set[str]) -> None:
        self._lock = Lock()
        self._tokens: dict[str, _TokenRecord] = {t: _TokenRecord() for t in valid_tokens}

    def redeem(self, token: str) -> str:
        """
        Returns "ok", "unknown", or "already_used" -- check-and-set under
        one lock acquisition so two concurrent requests for the same
        token cannot both succeed (the actual single-use guarantee, not
        just a documented intent).
        """
        with self._lock:
            record = self._tokens.get(token)
            if record is None:
                return "unknown"
            if record.redeemed:
                return "already_used"
            record.redeemed = True
            return "ok"


_TOKENS = _TokenStore(
    valid_tokens=set(
        filter(None, os.getenv("MOCK_VALID_ENROLLMENT_TOKENS", "dev-token-001").split(","))
    )
)

# device_id -> revoked?
_REVOKED_DEVICES: dict[str, bool] = {}


class EnrollRequest(BaseModel):
    csr_pem: str


class EnrollResponse(BaseModel):
    certificate_pem: str
    ca_chain_pem: str


@app.post("/enroll", status_code=status.HTTP_201_CREATED, response_model=EnrollResponse)
async def enroll(
    body: EnrollRequest,
    authorization: str = Header(default=""),
) -> EnrollResponse:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ")

    outcome = _TOKENS.redeem(token)
    if outcome == "unknown":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="unknown token")
    if outcome == "already_used":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="token already redeemed")

    csr = x509.load_pem_x509_csr(body.csr_pem.encode("ascii"))
    common_name = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    cert_pem = _issue_device_certificate(body.csr_pem, str(common_name))

    return EnrollResponse(
        certificate_pem=cert_pem.decode("ascii"),
        ca_chain_pem=_CA_CERT_PEM.decode("ascii"),
    )


@app.post("/reattest")
async def reattest(
    x_mock_device_id: str = Header(default="", alias="X-Mock-Device-Id"),
) -> dict:
    """
    LOCAL-DEV SHORTCUT (see module docstring): a real control plane
    authenticates the device via the mTLS client certificate the ingress
    terminated, not a plain header. Not fit for anything beyond this
    docker-compose network.
    """
    if not x_mock_device_id:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="no device identity presented"
        )
    if _REVOKED_DEVICES.get(x_mock_device_id, False):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="device revoked")
    return {"status": "ok"}


@app.post("/revoke/{device_id}")
async def revoke(device_id: str) -> dict:
    """Mock-only admin endpoint to exercise the revocation path locally."""
    _REVOKED_DEVICES[device_id] = True
    return {"revoked": device_id}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "component": "mock-control-plane"}


# ── Plain-HTTP info server (CA bundle fetch + healthcheck) ──────────────────
# Deliberately a SEPARATE, unauthenticated plain-HTTP listener (port 8080),
# not a route on the HTTPS app above -- serving the CA bundle over HTTPS
# with a client that must disable certificate verification to fetch it
# (the classic bootstrap chicken-and-egg: you'd need to already trust the
# CA to safely fetch the CA) would mean disabling TLS verification
# somewhere, which is a real risk pattern even for "just a public cert" --
# a MITM on this network could substitute a DIFFERENT CA's cert with no way
# for the fetcher to notice if verification is off. Serving it over plain
# HTTP instead is equally exposed to a network-level MITM, but does not
# create a False impression of a verified fetch, and does not require any
# TLS-verification-disabling code anywhere in this repo's tooling. The
# certificate itself is public, non-secret data by design (that's what a
# CA cert is for) -- the token and CSR/private key material NEVER touch
# this listener; only /enroll and /reattest (HTTPS, real cert, real
# verification) carry those.
class _PlainInfoHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # silence access logs for this trivial info server

    def do_GET(self) -> None:  # noqa: N802 -- stdlib method name
        if self.path == "/ca-bundle.pem":
            body = _CA_CERT_PEM
            self.send_response(200)
            self.send_header("Content-Type", "application/x-pem-file")
        elif self.path == "/health":
            body = b'{"status": "ok", "component": "mock-control-plane-info"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        else:
            self.send_response(404)
            body = b""
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _start_plain_info_server() -> None:
    server = HTTPServer(("0.0.0.0", 8080), _PlainInfoHandler)  # noqa: S104 -- container-internal only
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()


_start_plain_info_server()

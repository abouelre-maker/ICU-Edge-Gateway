"""
Integration Tests — CA Pinning (HAZARD-STREAM-010 server-authentication
leg).

Unlike test_enrollment_client.py (which uses httpx.MockTransport and never
touches real TLS), these tests stand up a REAL local HTTPS server on
127.0.0.1 with generated certificates, because CA pinning is a TLS-layer
guarantee -- a mocked transport bypasses TLS entirely and would prove
nothing about it. All certs are ephemeral, generated per-test via the
`cryptography` library (already a project dependency), and never written
outside tmp_path.
"""

from __future__ import annotations

import datetime
import ipaddress
import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from infrastructure.provisioning.enrollment_client import (
    DeviceEnrollmentClient,
    EnrollmentNetworkError,
)

_CSR_PEM = b"-----BEGIN CERTIFICATE REQUEST-----\nfake\n-----END CERTIFICATE REQUEST-----\n"


def _generate_ca(common_name: str = "Test Root CA"):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(hours=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _generate_leaf(ca_key, ca_cert, ip_san: str = "127.0.0.1"):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, ip_san)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(hours=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip_san))]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def _pem(obj) -> bytes:
    if isinstance(obj, x509.Certificate):
        return obj.public_bytes(serialization.Encoding.PEM)
    return obj.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


class _EnrollHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 -- stdlib signature
        pass  # silence test-server access logs

    def do_POST(self) -> None:  # noqa: N802 -- stdlib method name
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        body = json.dumps(
            {"certificate_pem": "issued-cert", "ca_chain_pem": "issued-ca"}
        ).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _start_https_server(tmp_path, leaf_key, leaf_cert) -> tuple[HTTPServer, int]:
    cert_path = tmp_path / "server.crt"
    key_path = tmp_path / "server.key"
    cert_path.write_bytes(_pem(leaf_cert))
    key_path.write_bytes(_pem(leaf_key))

    server = HTTPServer(("127.0.0.1", 0), _EnrollHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


@pytest.fixture
def pinned_server(tmp_path):
    """
    A real HTTPS server whose leaf cert is signed by `ca_cert` (returned
    alongside it), and the pinned CA bundle PEM path a client should trust
    to accept it.
    """
    ca_key, ca_cert = _generate_ca()
    leaf_key, leaf_cert = _generate_leaf(ca_key, ca_cert)
    server, port = _start_https_server(tmp_path, leaf_key, leaf_cert)

    ca_bundle_path = tmp_path / "pinned-ca.pem"
    ca_bundle_path.write_bytes(_pem(ca_cert))

    yield f"https://127.0.0.1:{port}", str(ca_bundle_path)

    server.shutdown()
    server.server_close()


@pytest.mark.integration
class TestCaPinningHappyPath:
    async def test_enroll_succeeds_when_ca_bundle_matches_server_cert(
        self, pinned_server
    ) -> None:
        bootstrap_url, ca_bundle_path = pinned_server
        client = DeviceEnrollmentClient(
            bootstrap_url, ca_bundle_path=ca_bundle_path, max_attempts=1
        )

        credentials = await client.enroll("valid-token", _CSR_PEM)

        assert credentials.certificate_pem == b"issued-cert"
        await client.aclose()


@pytest.mark.integration
class TestCaPinningRejectsWrongOrSelfSignedCa:
    async def test_enroll_rejects_server_cert_from_a_different_ca(
        self, tmp_path
    ) -> None:
        # Server is signed by CA "B" (self-signed leaf, standing in for
        # "any other publicly-trusted CA") -- client pins to a DIFFERENT
        # CA "A" it was actually configured to trust.
        wrong_ca_key, wrong_ca_cert = _generate_ca("Attacker/Unrelated CA")
        leaf_key, leaf_cert = _generate_leaf(wrong_ca_key, wrong_ca_cert)
        server, port = _start_https_server(tmp_path, leaf_key, leaf_cert)

        pinned_ca_key, pinned_ca_cert = _generate_ca("Real Control-Plane CA")
        ca_bundle_path = tmp_path / "pinned-ca.pem"
        ca_bundle_path.write_bytes(_pem(pinned_ca_cert))

        client = DeviceEnrollmentClient(
            f"https://127.0.0.1:{port}",
            ca_bundle_path=str(ca_bundle_path),
            max_attempts=1,
            base_backoff_seconds=0.001,
        )
        try:
            with pytest.raises(EnrollmentNetworkError):
                await client.enroll("valid-token", _CSR_PEM)
        finally:
            await client.aclose()
            server.shutdown()
            server.server_close()


@pytest.mark.integration
class TestCaPinningAgainstMalformedBundle:
    """
    Phase 5-Stream Section D edge case: the CA bundle FILE exists (unlike
    a missing-file case, which httpx would report as a plain "file not
    found" OSError before ever reaching TLS) but its CONTENTS are not
    valid PEM -- e.g. truncated during a write, or an operator accidentally
    pointed PROVISIONING_CA_BUNDLE_PATH at the wrong file. This must fail
    closed at construction time (no client is silently built that would
    fall back to permissive/system-default trust), not defer the failure
    to the first request or -- worse -- succeed with the pin silently not
    applied.
    """

    def test_construction_raises_on_malformed_pem_bundle(self, tmp_path) -> None:
        bad_bundle = tmp_path / "not-actually-pem.pem"
        bad_bundle.write_text("this is not a certificate\njust garbage text\n")

        with pytest.raises(ssl.SSLError):
            DeviceEnrollmentClient(
                "https://control-plane.example.org",
                ca_bundle_path=str(bad_bundle),
            )

    def test_construction_raises_on_empty_bundle_file(self, tmp_path) -> None:
        empty_bundle = tmp_path / "empty.pem"
        empty_bundle.write_text("")

        with pytest.raises(ssl.SSLError):
            DeviceEnrollmentClient(
                "https://control-plane.example.org",
                ca_bundle_path=str(empty_bundle),
            )


@pytest.mark.integration
class TestExpectedHostnamePin:
    """
    Distinct, independent-of-TLS check: `expected_hostname` guards against
    a tampered/misconfigured bootstrap_url pointing at an unexpected host
    -- see enrollment_client.py's HAZARD-STREAM-010 update docstring for
    why this is not the same guarantee as CA-pinned TLS hostname/SAN
    verification. No network call is made -- the check happens at
    construction time.
    """

    def test_construction_raises_on_hostname_mismatch(self) -> None:
        with pytest.raises(ValueError, match="does not match"):
            DeviceEnrollmentClient(
                "https://attacker-controlled.example.net/provisioning",
                expected_hostname="control-plane.acme-icu.org",
            )

    def test_construction_succeeds_on_hostname_match(self) -> None:
        client = DeviceEnrollmentClient(
            "https://control-plane.acme-icu.org/provisioning",
            expected_hostname="control-plane.acme-icu.org",
        )
        assert client is not None

"""
Generates the mock control plane's CA + its own HTTPS server leaf cert,
BEFORE uvicorn starts (see Dockerfile's CMD). Both live under /tmp inside
the container -- ephemeral, regenerated every container start, never
persisted, never used outside this docker-compose network.

Why the server needs its own leaf cert signed by the SAME CA it uses to
issue device certificates: config.get_provisioning_bootstrap_url()
requires https:// (fail-closed -- "the enrollment token and CSR must not
be sent over plaintext HTTP"), and the gateway's own CA-pinning
(HAZARD-STREAM-010 update, PROVISIONING_CA_BUNDLE_PATH) pins its TLS
trust to this exact CA -- so this mock's own HTTPS listener must present
a cert this CA actually issued, or the gateway's own pinning would
correctly refuse the connection. Using ONE CA for both the server's own
TLS identity and the device certs it issues also keeps the local trust
chain honest: it's the same shape a real control plane has (its own
front-door TLS cert is typically issued by a public/ops CA, DIFFERENT
from the private CA it uses for device identities -- see infra/terraform/
DESIGN.md's note on this if that distinction matters for your deployment;
this mock simplifies to one CA for both, which is fine for local dev but
NOT how infra/terraform/modules/ca is set up for production).
"""

from __future__ import annotations

import datetime
import ipaddress
import os

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

# MOCK_CP_CERT_DIR: /tmp inside the container by default (real deployment
# path -- see Dockerfile). Overridable so tests/integration/
# test_mock_control_plane_contract.py can redirect both this module's and
# app.py's paths to the SAME test-owned directory without them drifting
# apart -- both modules read the same env var, rather than each having
# their own hardcoded constant a test would have to patch separately.
_CERT_DIR = os.getenv("MOCK_CP_CERT_DIR", "/tmp")
_CA_KEY_PATH = os.path.join(_CERT_DIR, "ca.key")
_CA_CERT_PATH = os.path.join(_CERT_DIR, "ca.crt")
_SERVER_KEY_PATH = os.path.join(_CERT_DIR, "server.key")
_SERVER_CERT_PATH = os.path.join(_CERT_DIR, "server.crt")


def _write_pem(path: str, obj) -> None:
    if isinstance(obj, x509.Certificate):
        data = obj.public_bytes(serialization.Encoding.PEM)
    else:
        data = obj.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    with open(path, "wb") as fh:
        fh.write(data)


def main() -> None:
    now = datetime.datetime.now(datetime.timezone.utc)

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "ICU Edge Gateway Mock Dev CA")]
    )
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(hours=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    server_key = ec.generate_private_key(ec.SECP256R1())
    server_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "mock-control-plane")]
    )
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(hours=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    # docker-compose service name -- how the gateway
                    # container reaches this one on the compose network.
                    x509.DNSName("mock-control-plane"),
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    _write_pem(_CA_KEY_PATH, ca_key)
    _write_pem(_CA_CERT_PATH, ca_cert)
    _write_pem(_SERVER_KEY_PATH, server_key)
    _write_pem(_SERVER_CERT_PATH, server_cert)
    print("[generate_certs] mock CA + server leaf cert written to /tmp")


if __name__ == "__main__":
    main()

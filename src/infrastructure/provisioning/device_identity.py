"""
Device Identity — Local Keypair Generation and CSR Construction.

Phase 5 Section B, step 1a/1b. This module is the ONLY place in the
codebase that touches the device's private key material.

TRUST CHAIN (be precise -- this is not "mTLS from a blank device"):
  1. The device generates an ECDSA P-256 keypair LOCALLY, at container
     startup, into a mounted volume (config.get_cert_store_path()) -- never
     at image-build time, never written into any image layer. If this
     process is killed and restarted before enrollment completes, a NEW
     keypair is generated (the old one is discarded with it, since it was
     never persisted anywhere durable outside this same volume).
  2. A CSR is built from that key and sent, over a SERVER-authenticated
     (not yet mutual) TLS connection, to the control plane's bootstrap
     endpoint, alongside a single-use enrollment token
     (enrollment_client.py). The private key itself never leaves the
     device -- only the CSR (a public-key + identity claim, standard X.509
     semantics) is transmitted.
  3. Only AFTER the control plane issues a certificate back does mTLS
     begin (enrollment_client.py / cert_store.py). Before that point, the
     device has no certificate to present as a client, by construction.

ISO 14971 HAZARD-STREAM-010 (PROPOSED -- pending human security/risk-
management sign-off; see enrollment_client.py for the full hazard
analysis): this module's only responsibility relevant to that hazard is
NEVER logging, printing, or otherwise exposing the private key -- callers
must not do so either.
"""

from __future__ import annotations

import contextlib
import os
import stat

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

# P-256 (secp256r1): the codebase's mandated minimum is "ECDSA (or RSA-2048
# minimum)" -- P-256 is the conventional ECDSA choice matching that bar and
# is universally supported by TLS stacks, with far smaller keys/CSRs than
# RSA-2048.
_CURVE = ec.SECP256R1()


def generate_private_key() -> ec.EllipticCurvePrivateKey:
    """Generate a fresh ECDSA P-256 private key. Never persisted by this
    function -- see CertStore.load_or_generate_key() for the
    generate-once-and-persist-to-a-mounted-volume path callers should
    normally use instead of calling this directly."""
    return ec.generate_private_key(_CURVE)


def serialize_private_key(private_key: ec.EllipticCurvePrivateKey) -> bytes:
    """PKCS#8 PEM, unencrypted. Encryption-at-rest for this file is a
    filesystem/volume-level concern (e.g. an encrypted PVC or a Kubernetes
    Secret backed by KMS-encrypted etcd) -- not re-implemented here."""
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def load_private_key(pem_bytes: bytes) -> ec.EllipticCurvePrivateKey:
    key = serialization.load_pem_private_key(pem_bytes, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ValueError(
            "Loaded private key is not an EC private key -- "
            f"got {type(key).__name__}."
        )
    return key


def write_private_key_file(path: str, private_key: ec.EllipticCurvePrivateKey) -> None:
    """
    Write the private key to `path` with owner-only permissions (0600).

    The key must never be world- or group-readable: any other process
    (or, on a shared host, any other container sharing the volume) that
    can read this file can impersonate this device to the control plane.
    os.chmod(0o600) is a best-effort POSIX permission; it has no effect on
    Windows filesystems (this repo's edge target is Linux/Alpine
    containers, so this is the production-relevant path -- Windows dev
    environments running this function get a file with default
    permissions, not a security regression for the actual deployment
    target).
    """
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    pem = serialize_private_key(private_key)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(pem)
    finally:
        if hasattr(os, "chmod"):
            with contextlib.suppress(OSError):
                # best-effort on platforms/filesystems that don't support it
                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def build_csr(
    private_key: ec.EllipticCurvePrivateKey,
    common_name: str,
    organization: str = "ICU-Edge-Gateway",
) -> bytes:
    """
    Build a PEM-encoded PKCS#10 Certificate Signing Request identifying
    this device by `common_name` (expected to be a stable device identifier,
    e.g. a hardware serial or a pre-provisioned device UUID -- callers
    decide what that is; this module has no opinion beyond "it's a
    string").
    """
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(subject)
        .sign(private_key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM)

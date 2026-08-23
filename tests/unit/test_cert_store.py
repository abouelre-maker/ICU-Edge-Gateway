"""
Unit Tests — infrastructure.provisioning.cert_store.

Covers on-disk credential storage, validity windows, and the
revocation/quarantine path (HAZARD-STREAM-011). Certificates used here are
minted locally with a throwaway self-signed CA (this module has no opinion
about who issued a certificate -- it only reads notBefore/notAfter).
"""

from __future__ import annotations

import datetime

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from infrastructure.provisioning.cert_store import CertStore, IssuedCredentials


def _make_certificate(
    subject_key: ec.EllipticCurvePrivateKey,
    *,
    not_before: datetime.datetime,
    not_after: datetime.datetime,
) -> bytes:
    """Self-signed test certificate -- CertStore never validates the
    issuer/chain itself, only notBefore/notAfter, so self-signed is fine
    here."""
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-device")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(subject_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .sign(subject_key, hashes.SHA256())
    )
    return cert.public_bytes(encoding=serialization.Encoding.PEM)


@pytest.fixture
def store(tmp_path) -> CertStore:
    return CertStore(str(tmp_path / "pki"))


class TestHasValidIdentity:
    def test_false_when_nothing_present(self, store: CertStore) -> None:
        assert store.has_valid_identity() is False

    def test_false_when_only_key_present(self, store: CertStore) -> None:
        store.load_or_generate_key()
        assert store.has_valid_identity() is False

    def test_true_for_unexpired_certificate(self, store: CertStore) -> None:
        key = store.load_or_generate_key()
        now = datetime.datetime(2026, 8, 9, tzinfo=datetime.timezone.utc)
        cert_pem = _make_certificate(
            key,
            not_before=now - datetime.timedelta(hours=1),
            not_after=now + datetime.timedelta(days=30),
        )
        store.write_issued_credentials(
            IssuedCredentials(certificate_pem=cert_pem, ca_chain_pem=cert_pem)
        )
        assert store.has_valid_identity(now=now) is True

    def test_false_for_expired_certificate(self, store: CertStore) -> None:
        key = store.load_or_generate_key()
        now = datetime.datetime(2026, 8, 9, tzinfo=datetime.timezone.utc)
        cert_pem = _make_certificate(
            key,
            not_before=now - datetime.timedelta(days=30),
            not_after=now - datetime.timedelta(days=1),  # expired yesterday
        )
        store.write_issued_credentials(
            IssuedCredentials(certificate_pem=cert_pem, ca_chain_pem=cert_pem)
        )
        assert store.has_valid_identity(now=now) is False

    def test_false_for_not_yet_valid_certificate(self, store: CertStore) -> None:
        key = store.load_or_generate_key()
        now = datetime.datetime(2026, 8, 9, tzinfo=datetime.timezone.utc)
        cert_pem = _make_certificate(
            key,
            not_before=now + datetime.timedelta(days=1),  # starts tomorrow
            not_after=now + datetime.timedelta(days=30),
        )
        store.write_issued_credentials(
            IssuedCredentials(certificate_pem=cert_pem, ca_chain_pem=cert_pem)
        )
        assert store.has_valid_identity(now=now) is False


class TestLoadOrGenerateKey:
    def test_generates_and_persists_on_first_call(self, store: CertStore) -> None:
        key = store.load_or_generate_key()
        assert key is not None
        import os

        assert os.path.exists(store.key_path)

    def test_second_call_loads_the_same_key(self, store: CertStore) -> None:
        key_a = store.load_or_generate_key()
        key_b = store.load_or_generate_key()
        assert (
            key_a.private_numbers().private_value
            == key_b.private_numbers().private_value
        )


class TestQuarantine:
    def test_quarantine_makes_identity_invalid(self, store: CertStore) -> None:
        key = store.load_or_generate_key()
        now = datetime.datetime(2026, 8, 9, tzinfo=datetime.timezone.utc)
        cert_pem = _make_certificate(
            key,
            not_before=now - datetime.timedelta(hours=1),
            not_after=now + datetime.timedelta(days=30),
        )
        store.write_issued_credentials(
            IssuedCredentials(certificate_pem=cert_pem, ca_chain_pem=cert_pem)
        )
        assert store.has_valid_identity(now=now) is True

        store.quarantine()

        assert store.has_valid_identity(now=now) is False

    def test_quarantine_preserves_the_private_key(self, store: CertStore) -> None:
        key = store.load_or_generate_key()
        now = datetime.datetime(2026, 8, 9, tzinfo=datetime.timezone.utc)
        cert_pem = _make_certificate(
            key,
            not_before=now - datetime.timedelta(hours=1),
            not_after=now + datetime.timedelta(days=30),
        )
        store.write_issued_credentials(
            IssuedCredentials(certificate_pem=cert_pem, ca_chain_pem=cert_pem)
        )

        store.quarantine()

        reloaded = store.load_or_generate_key()
        assert (
            reloaded.private_numbers().private_value == key.private_numbers().private_value
        )

    def test_quarantine_on_absent_certificate_does_not_raise(
        self, store: CertStore
    ) -> None:
        store.quarantine()  # nothing to quarantine -- must not error
        assert store.has_valid_identity() is False

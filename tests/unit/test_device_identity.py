"""
Unit Tests — infrastructure.provisioning.device_identity.

Covers local keypair generation/persistence and CSR construction. Does not
touch the network (that's enrollment_client.py's tests) -- this module's
job stops at "produce a key and a CSR," per its own docstring.
"""

from __future__ import annotations

import os

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from infrastructure.provisioning import device_identity


class TestGeneratePrivateKey:
    def test_generates_ec_p256_key(self) -> None:
        key = device_identity.generate_private_key()
        assert isinstance(key, ec.EllipticCurvePrivateKey)
        assert key.curve.name == "secp256r1"

    def test_two_calls_produce_different_keys(self) -> None:
        key_a = device_identity.generate_private_key()
        key_b = device_identity.generate_private_key()
        assert key_a.private_numbers().private_value != key_b.private_numbers().private_value


class TestKeySerializationRoundTrip:
    def test_serialize_then_load_round_trips(self) -> None:
        key = device_identity.generate_private_key()
        pem = device_identity.serialize_private_key(key)
        loaded = device_identity.load_private_key(pem)
        assert loaded.private_numbers().private_value == key.private_numbers().private_value

    def test_load_rejects_non_ec_key(self) -> None:
        from cryptography.hazmat.primitives.asymmetric import rsa

        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        from cryptography.hazmat.primitives import serialization

        pem = rsa_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with pytest.raises(ValueError, match="not an EC private key"):
            device_identity.load_private_key(pem)


class TestWritePrivateKeyFile:
    def test_writes_loadable_pem_file(self, tmp_path) -> None:
        key = device_identity.generate_private_key()
        path = str(tmp_path / "nested" / "device.key")

        device_identity.write_private_key_file(path, key)

        assert os.path.exists(path)
        with open(path, "rb") as fh:
            loaded = device_identity.load_private_key(fh.read())
        assert loaded.private_numbers().private_value == key.private_numbers().private_value

    def test_overwrites_existing_file(self, tmp_path) -> None:
        path = str(tmp_path / "device.key")
        key_a = device_identity.generate_private_key()
        key_b = device_identity.generate_private_key()

        device_identity.write_private_key_file(path, key_a)
        device_identity.write_private_key_file(path, key_b)

        with open(path, "rb") as fh:
            loaded = device_identity.load_private_key(fh.read())
        assert loaded.private_numbers().private_value == key_b.private_numbers().private_value


class TestBuildCsr:
    def test_csr_carries_common_name_and_org(self) -> None:
        from cryptography import x509

        key = device_identity.generate_private_key()
        csr_pem = device_identity.build_csr(
            key, common_name="edge-device-001", organization="Test-Org"
        )

        csr = x509.load_pem_x509_csr(csr_pem)
        assert csr.is_signature_valid
        cn = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        org = csr.subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)[0].value
        assert cn == "edge-device-001"
        assert org == "Test-Org"

    def test_csr_public_key_matches_private_key(self) -> None:
        from cryptography import x509

        key = device_identity.generate_private_key()
        csr_pem = device_identity.build_csr(key, common_name="edge-device-002")
        csr = x509.load_pem_x509_csr(csr_pem)

        csr_public_numbers = csr.public_key().public_numbers()  # type: ignore[union-attr]
        key_public_numbers = key.public_key().public_numbers()
        assert csr_public_numbers == key_public_numbers

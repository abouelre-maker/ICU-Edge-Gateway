"""
Device-Identity Provisioning — Phase 5 Section B.

Zero-touch edge enrollment: a device generates its own keypair locally,
proves itself to the control plane with a single-use enrollment token, and
receives a short-lived mTLS device certificate in return. See
device_identity.py (keypair/CSR), cert_store.py (on-disk credential
storage), enrollment_client.py (the enrollment HTTP protocol + revocation
re-attestation), and bootstrap.py (orchestration entrypoint).
"""

from __future__ import annotations

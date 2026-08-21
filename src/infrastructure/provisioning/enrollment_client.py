"""
DeviceEnrollmentClient — Enrollment Handshake + Revocation Re-Attestation.

Phase 5 Section B, steps 1b-1e. Implements the device side of the
enrollment protocol:
  1. Server-authenticated TLS connection to the control plane's bootstrap
     endpoint (standard httpx TLS verification against the system/CA
     bundle -- this is NOT yet mutual TLS; the device has no certificate
     to present at this point, by construction -- see device_identity.py).
  2. POST {enrollment_token, csr_pem} to "{bootstrap_url}/enroll".
  3. The control plane validates the token (one-time use, tenant-scoped,
     expiring) and either issues a device certificate + CA chain, or
     rejects the request (401/403 = invalid/expired token, 409 = token
     already used/replayed).
  4. mTLS begins only after this handshake succeeds -- see cert_store.py
     and this module's reattest().

ISO 14971 HAZARD-STREAM-010 (PROPOSED -- pending human security/risk-
management sign-off; new hazard for new code, raised per explicit request
to scrutinize this endpoint the same way the missing-auth finding on
POST /api/v1/fhir/Subscription was scrutinized):
  The bootstrap endpoint (control-plane side, not implemented in this
  repo -- this repo is the DEVICE/client side of the protocol) is the
  second credential-accepting surface in this codebase's threat model,
  after fhir_subscription.py. An attacker who obtains or guesses an
  enrollment token can enroll an illegitimate device and receive a valid
  mTLS certificate, i.e. token brute-force or replay IS device
  impersonation, not merely unauthorized read/write of a resource.
  Split of responsibility:
    - PRIMARY mitigation is necessarily control-plane-side (out of scope
      of this repo): the token must be single-use (invalidated on first
      successful redemption -- a replay of an already-consumed token must
      be rejected, distinguishably, as 409 here), short-TTL, and
      rate-limited/brute-force-protected by the control plane itself,
      since this device-side client cannot enforce any of that against a
      server it does not control.
    - What THIS module does, on the device side, to avoid being a source
      of abuse and to leave an audit trail:
        - Every enrollment attempt is logged via structlog (attempt
          number, target URL, outcome) -- the token value and CSR/key
          material are NEVER included in any log line.
        - Retries are bounded (config.get_provisioning_max_enroll_attempts(),
          default 5) with exponential backoff -- a device stuck in a
          crash-loop before enrollment completes cannot hammer the
          bootstrap endpoint at an unbounded rate.
        - A 401/403/409 (token rejected) response is NOT retried at all --
          retrying a rejected token is either pointless (invalid/expired)
          or itself contributes to a replay pattern (reused) that the
          control plane's own abuse detection should be watching for; this
          client stops immediately and surfaces the rejection instead of
          silently trying again.
  NOT mitigated here: rate-limiting or brute-force protection of the
  control plane's endpoint ITSELF -- that is server-side and out of this
  repo's scope, same as the SSRF-endpoint-owner distinction already drawn
  in url_safety.py's docstring. Flagged for human review: the control
  plane implementation (wherever it lives) must independently rate-limit
  per-token and per-source-IP attempts.

  UPDATE (server-authentication leg -- narrows, does NOT close, this
  hazard; still PROPOSED, pending human sign-off): the handshake described
  above was originally server-authenticated against the OS/system default
  CA trust store, not the control plane's own CA specifically -- meaning
  ANY publicly-trusted certificate, not just the real control plane's,
  would be accepted. `ca_bundle_path` (see __init__, wired from
  config.get_provisioning_ca_bundle_path(), itself fail-closed) now pins
  TLS trust to the control plane's specific CA bundle instead, closing
  that specific gap. `expected_hostname`, when supplied from a source
  independent of `bootstrap_url` itself, additionally guards against a
  tampered/misconfigured bootstrap_url pointing at an unexpected host
  while still naming a hostname that CA pinning alone wouldn't catch (CA
  pinning proves "this cert is trusted by the control plane's CA", not
  "bootstrap_url is the host we meant to configure"). Standard TLS
  hostname/SAN verification against the pinned CA happens automatically
  once `verify=` points at a real CA bundle -- that part requires no
  additional code here.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import structlog

from infrastructure.provisioning.cert_store import IssuedCredentials

_log: structlog.BoundLogger = structlog.get_logger(__name__)

_DEFAULT_BASE_BACKOFF_SECONDS = 1.0
_DEFAULT_MAX_BACKOFF_SECONDS = 30.0
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 15.0

# Status codes meaning "the token itself was rejected" -- never retried,
# because retrying cannot help (invalid/expired) or would itself look like
# a replay attempt (already used).
_TOKEN_REJECTED_STATUS_REASONS: dict[int, str] = {
    401: "invalid_or_unauthenticated",
    403: "forbidden",
    409: "already_used",
}


class EnrollmentError(Exception):
    """Base class for enrollment handshake failures."""


class TokenRejectedError(EnrollmentError):
    """
    The control plane rejected the enrollment token itself (not a
    transient network/server problem). `reason` is one of
    _TOKEN_REJECTED_STATUS_REASONS's values. NOT retried by
    DeviceEnrollmentClient.enroll() -- callers must obtain a new token
    (which requires human/operator action, since tokens are single-use by
    design) rather than loop on this.
    """

    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason
        super().__init__(f"Enrollment token rejected ({reason}, HTTP {status_code}).")


class EnrollmentNetworkError(EnrollmentError):
    """Raised after PROVISIONING_MAX_ENROLL_ATTEMPTS consecutive
    network/transient-server failures. Distinct from TokenRejectedError so
    callers (and audit logs) can tell "the control plane was unreachable"
    apart from "the control plane said no"."""


@dataclass(frozen=True)
class ReattestationResult:
    """Outcome of a single reattest() call."""

    revoked: bool
    status_code: int


class DeviceEnrollmentClient:
    """
    Device-side enrollment protocol client.

    `http_client` is injectable (httpx.AsyncClient with a MockTransport, in
    tests) so no real network call is required to exercise this class --
    mirrors the pattern already used by subscription_dispatcher.py's tests.
    """

    def __init__(
        self,
        bootstrap_url: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        ca_bundle_path: str | None = None,
        expected_hostname: str | None = None,
        max_attempts: int = 5,
        base_backoff_seconds: float = _DEFAULT_BASE_BACKOFF_SECONDS,
        max_backoff_seconds: float = _DEFAULT_MAX_BACKOFF_SECONDS,
    ) -> None:
        """
        `ca_bundle_path` and `expected_hostname` are ignored when
        `http_client` is injected (tests own their own transport) -- they
        only affect the httpx.AsyncClient this constructor builds itself.

        `expected_hostname`, if given, MUST come from a source independent
        of `bootstrap_url` (e.g. a separate pinned config value) -- passing
        `urlparse(bootstrap_url).hostname` back in here is a no-op check
        that proves nothing, since it will always match itself.
        """
        if max_attempts < 1:
            raise ValueError(f"max_attempts must be >= 1. Got {max_attempts}.")
        self._bootstrap_url = bootstrap_url.rstrip("/")

        if expected_hostname is not None:
            actual_hostname = urlparse(self._bootstrap_url).hostname
            if actual_hostname != expected_hostname:
                raise ValueError(
                    "bootstrap_url hostname "
                    f"{actual_hostname!r} does not match the independently "
                    f"pinned control-plane hostname {expected_hostname!r} "
                    "(HAZARD-STREAM-010 server-authentication check) -- "
                    "refusing to construct an enrollment client rather than "
                    "connect to an unexpected host."
                )

        # `ca_bundle_path` is this device's root of trust for every mTLS
        # connection it will ever make -- the fleet-wide blast radius of
        # that trust (root CA private-key custody and compromise) is ISO
        # 14971 HAZARD-STREAM-012, tracked at the infrastructure layer that
        # actually runs the CA, not here: see
        # infra/terraform/modules/ca/main.tf's module-header docstring for
        # the full hazard record. This comment exists so a reader who finds
        # HAZARD-STREAM-012 from the risk register (or from here) can reach
        # the other side without a register-to-nowhere dead end -- this
        # module does not re-derive or restate that analysis.
        self._client = http_client or httpx.AsyncClient(
            timeout=_DEFAULT_REQUEST_TIMEOUT_SECONDS,
            verify=ca_bundle_path if ca_bundle_path else True,
        )
        self._owns_client = http_client is None
        self._max_attempts = max_attempts
        self._base_backoff_seconds = base_backoff_seconds
        self._max_backoff_seconds = max_backoff_seconds

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def enroll(self, enrollment_token: str, csr_pem: bytes) -> IssuedCredentials:
        """
        Redeem `enrollment_token` for a device certificate. Raises
        TokenRejectedError immediately on a rejected token (no retry) or
        EnrollmentNetworkError after exhausting max_attempts on transient
        failures. Never logs `enrollment_token` or `csr_pem`.
        """
        url = f"{self._bootstrap_url}/enroll"
        last_error: Exception | None = None

        for attempt in range(1, self._max_attempts + 1):
            _log.info(
                "provisioning.enroll.attempt",
                attempt=attempt,
                max_attempts=self._max_attempts,
                url=url,
            )
            try:
                response = await self._client.post(
                    url,
                    headers={"Authorization": f"Bearer {enrollment_token}"},
                    json={"csr_pem": csr_pem.decode("ascii")},
                )
            except httpx.HTTPError as exc:
                last_error = exc
                _log.warning(
                    "provisioning.enroll.network_error",
                    attempt=attempt,
                    error_type=type(exc).__name__,
                )
                await self._sleep_backoff(attempt)
                continue

            if response.status_code in _TOKEN_REJECTED_STATUS_REASONS:
                reason = _TOKEN_REJECTED_STATUS_REASONS[response.status_code]
                _log.warning(
                    "provisioning.enroll.token_rejected",
                    attempt=attempt,
                    status_code=response.status_code,
                    reason=reason,
                )
                raise TokenRejectedError(response.status_code, reason)

            if response.status_code == 201:
                body = response.json()
                _log.info("provisioning.enroll.success", attempt=attempt)
                return IssuedCredentials(
                    certificate_pem=body["certificate_pem"].encode("ascii"),
                    ca_chain_pem=body["ca_chain_pem"].encode("ascii"),
                )

            # Any other status (5xx, unexpected 4xx) is treated as
            # transient/server-side -- retried, not raised immediately,
            # since (unlike a token rejection) it is not necessarily
            # permanent.
            last_error = EnrollmentNetworkError(
                f"Unexpected status {response.status_code} from {url}."
            )
            _log.warning(
                "provisioning.enroll.unexpected_status",
                attempt=attempt,
                status_code=response.status_code,
            )
            await self._sleep_backoff(attempt)

        _log.error(
            "provisioning.enroll.exhausted",
            max_attempts=self._max_attempts,
        )
        raise EnrollmentNetworkError(
            f"Enrollment failed after {self._max_attempts} attempts against {url}."
        ) from last_error

    async def reattest(self, mtls_client: httpx.AsyncClient) -> ReattestationResult:
        """
        Periodic revocation check (HAZARD-STREAM-011): present the
        device's current mTLS identity to "{bootstrap_url}/reattest".
        `mtls_client` must already be configured with the device's issued
        client certificate (cert_store.py) -- this method does not build
        one, since the mTLS context is a deployment-level concern (which
        TLS library/version, cert reload behavior, etc.) kept out of the
        enrollment protocol logic itself.
        """
        url = f"{self._bootstrap_url}/reattest"
        try:
            response = await mtls_client.post(url)
        except httpx.HTTPError as exc:
            _log.warning(
                "provisioning.reattest.network_error", error_type=type(exc).__name__
            )
            # A network failure is NOT treated as revocation -- see
            # cert_store.py's HAZARD-STREAM-011 docstring: an appliance
            # that cannot reach the control plane keeps its last-known-good
            # certificate rather than being fail-closed on connectivity
            # alone, which would let a WAN outage masquerade as revocation.
            raise EnrollmentNetworkError(
                f"Re-attestation call to {url} failed: {exc}"
            ) from exc

        revoked = response.status_code in (401, 403)
        if revoked:
            _log.warning(
                "provisioning.reattest.revoked", status_code=response.status_code
            )
        else:
            _log.info(
                "provisioning.reattest.ok", status_code=response.status_code
            )
        return ReattestationResult(revoked=revoked, status_code=response.status_code)

    async def _sleep_backoff(self, attempt: int) -> None:
        delay = min(
            self._base_backoff_seconds * (2 ** (attempt - 1)),
            self._max_backoff_seconds,
        )
        await asyncio.sleep(delay)

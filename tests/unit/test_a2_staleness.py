"""
A2 — staleness, future and unparseable timestamps; effective time.

Decisions (delegated 2026-09-29, pending clinical review; regulatory/findings/A2.md):
  Q1(b) per-parameter staleness windows are mandatory configuration; with any
        window unset the service refuses to start and the gate withholds scores.
  Q3    future-timestamp tolerance defaults to 60 s (configurable).
  N-03  an unparseable/absent HL7 timestamp is UNPARSEABLE_TIMESTAMP, never now().
Window values used here are test fixtures, not clinical values.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from domain.entities.patient_context import PatientContext
from domain.entities.score_outcome import ReasonCode, ScoreOutcome
from domain.entities.vital_sign import (
    AVPULevel,
    VitalSignSample,
    VitalSignType,
    VitalSignUnit,
)
from domain.services.scoring_gate import (
    ScoringGate,
    ScoringPolicy,
    policy_from_environment,
)
from domain.services.vitals_orchestrator import VitalsOrchestrator
from infrastructure.adapters.hl7v2_adapter import HL7v2Adapter
from infrastructure.fhir.bundle_assembler import BundleAssembler

_T = VitalSignType
_U = VitalSignUnit
_CTX = PatientContext(patient_id="PT-A2")
_NOW = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)
_WINDOW = timedelta(minutes=30)  # fixture value only
_POLICY = ScoringPolicy(
    staleness_windows={t: _WINDOW for t in ScoringPolicy.REQUIRED_TYPES},
    future_tolerance=timedelta(seconds=60),
)


def _orch(policy: ScoringPolicy | None = _POLICY) -> VitalsOrchestrator:
    return VitalsOrchestrator(
        gate=ScoringGate(policy_provider=lambda: policy, clock=lambda: _NOW)
    )


def _seven(ts: datetime, **ts_overrides: datetime) -> list[VitalSignSample]:
    spec = [
        (_T.RESPIRATORY_RATE, 16.0, _U.BREATHS_PER_MIN),
        (_T.SPO2, 97.0, _U.PERCENT),
        (_T.SYSTOLIC_BP, 120.0, _U.MMHG),
        (_T.HEART_RATE, 75.0, _U.BPM),
        (_T.TEMPERATURE_CELSIUS, 37.0, _U.CELSIUS),
        (_T.SUPPLEMENTAL_O2, 0.0, _U.BOOLEAN),
    ]
    out = [
        VitalSignSample(
            vital_sign_type=t, value=v, unit=u, timestamp=ts_overrides.get(t.name, ts)
        )
        for t, v, u in spec
    ]
    out.append(
        VitalSignSample(
            vital_sign_type=_T.CONSCIOUSNESS, value=0.0, unit=_U.AVPU_SCALE,
            timestamp=ts_overrides.get("CONSCIOUSNESS", ts), avpu_level=AVPULevel.ALERT,
        )
    )
    return out


class TestStaleness:
    def test_fresh_inputs_are_scored(self) -> None:
        r = _orch().analyse(_seven(_NOW - timedelta(minutes=5)), _CTX)
        assert r.assessment.outcome is ScoreOutcome.SCORED
        assert r.news2_score is not None

    def test_two_day_old_respiratory_rate_is_stale(self) -> None:
        r = _orch().analyse(
            _seven(_NOW, RESPIRATORY_RATE=_NOW - timedelta(days=2)), _CTX
        )
        assert r.news2_score is None
        assert r.assessment.outcome is ScoreOutcome.INCOMPLETE
        stale = [f for f in r.assessment.findings if f.code is ReasonCode.STALE_OBSERVATION]
        assert [f.parameter for f in stale] == [_T.RESPIRATORY_RATE]

    @pytest.mark.parametrize("name", ["CONSCIOUSNESS", "SUPPLEMENTAL_O2"])
    def test_stale_categorical_inputs_are_stale_too(self, name: str) -> None:
        r = _orch().analyse(_seven(_NOW, **{name: _NOW - timedelta(hours=3)}), _CTX)
        assert ReasonCode.STALE_OBSERVATION.value in r.assessment.reason_codes
        assert r.news2_score is None

    def test_future_timestamp_beyond_tolerance_is_incomplete(self) -> None:
        r = _orch().analyse(_seven(_NOW, HEART_RATE=_NOW + timedelta(minutes=5)), _CTX)
        assert r.news2_score is None
        assert ReasonCode.FUTURE_TIMESTAMP.value in r.assessment.reason_codes

    def test_future_timestamp_within_tolerance_is_accepted(self) -> None:
        r = _orch().analyse(_seven(_NOW, HEART_RATE=_NOW + timedelta(seconds=30)), _CTX)
        assert r.assessment.outcome is ScoreOutcome.SCORED

    def test_unset_policy_withholds_score(self) -> None:
        r = _orch(policy=None).analyse(_seven(_NOW), _CTX)
        assert r.news2_score is None
        assert ReasonCode.STALENESS_POLICY_UNSET.value in r.assessment.reason_codes


class TestPolicyFromEnvironment:
    def test_any_window_unset_gives_no_policy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NEWS2_STALENESS_WINDOW_HEART_RATE_SECONDS", raising=False)
        assert policy_from_environment() is None

    def test_all_windows_set_gives_policy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for t in ScoringPolicy.REQUIRED_TYPES:
            monkeypatch.setenv(f"NEWS2_STALENESS_WINDOW_{t.name}_SECONDS", "900")
        monkeypatch.delenv("FUTURE_TIMESTAMP_TOLERANCE_SECONDS", raising=False)
        policy = policy_from_environment()
        assert policy is not None
        assert policy.staleness_windows[_T.HEART_RATE] == timedelta(seconds=900)
        assert policy.future_tolerance == timedelta(seconds=60)  # default (Q3)

    @pytest.mark.parametrize("bad", ["0", "-5", "abc"])
    def test_invalid_window_is_rejected(self, monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
        for t in ScoringPolicy.REQUIRED_TYPES:
            monkeypatch.setenv(f"NEWS2_STALENESS_WINDOW_{t.name}_SECONDS", "900")
        monkeypatch.setenv("NEWS2_STALENESS_WINDOW_SPO2_SECONDS", bad)
        with pytest.raises(ValueError):
            policy_from_environment()


class TestServiceRefusesToStart:
    async def test_lifespan_fails_closed_when_a_window_is_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from main import create_app  # noqa: PLC0415

        monkeypatch.delenv("NEWS2_STALENESS_WINDOW_TEMPERATURE_CELSIUS_SECONDS", raising=False)
        app = create_app()
        with pytest.raises(RuntimeError, match="NEWS2_STALENESS_WINDOW_TEMPERATURE_CELSIUS_SECONDS"):
            async with app.router.lifespan_context(app):
                pass


_MSH = "MSH|^~\\&|MON|ICU|EHR|HOSP|{ts}||ORU^R01|C1|P|2.5.1\rPID|1||P1^^^H^MR\r"


class TestUnparseableTimestamps:
    def test_unparseable_obx14_is_reported_never_now(self) -> None:
        res = HL7v2Adapter().parse(
            _MSH.format(ts="20260929110000")
            + "OBX|1|NM|8867-4^HR^LN||75|/min|||||F|||NOT-A-DATE"
        )
        assert res.samples == ()
        codes = [f.code for f in res.findings]
        assert ReasonCode.UNPARSEABLE_TIMESTAMP in codes

    def test_missing_msh7_and_obx14_is_reported_and_never_scored(self) -> None:
        # Interim behaviour (HD-E6 entry A2-1): sample kept with a receipt-time
        # placeholder, but the finding forces INCOMPLETE — never a score.
        res = HL7v2Adapter().parse(
            _MSH.format(ts="") + "OBX|1|NM|8867-4^HR^LN||75|/min|||||F"
        )
        assert ReasonCode.UNPARSEABLE_TIMESTAMP in [f.code for f in res.findings]
        r = VitalsOrchestrator().analyse(
            list(res.samples), _CTX, upstream_findings=res.findings
        )
        assert r.news2_score is None
        assert r.assessment.outcome is ScoreOutcome.INCOMPLETE

    def test_valid_msh7_is_used_when_obx14_absent(self) -> None:
        res = HL7v2Adapter().parse(
            _MSH.format(ts="20260929110000") + "OBX|1|NM|8867-4^HR^LN||75|/min|||||F"
        )
        assert len(res.samples) == 1
        assert res.samples[0].timestamp == datetime(2026, 9, 29, 11, 0, tzinfo=timezone.utc)
        assert res.findings == ()


class TestEffectiveTime:
    def test_news2_effective_time_is_observation_time_not_now(self) -> None:
        obs_ts = _NOW - timedelta(minutes=7)
        r = _orch().analyse(_seven(obs_ts), _CTX)
        assert r.assessment.observation_time == obs_ts
        bundle = BundleAssembler().assemble(r, _CTX)
        news2 = [
            e["resource"]
            for e in bundle["entry"]
            if e["resource"]["resourceType"] == "Observation"
            and e["resource"]["code"]["coding"][0]["code"] == "1239842005"
        ]
        assert len(news2) == 1
        assert news2[0]["effectiveDateTime"] == "2026-09-29T11:53:00Z"
        assert "issued" in news2[0]

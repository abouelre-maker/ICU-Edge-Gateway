"""
Regulatory Test — ISO 14971 HAZARD-DSP-007 Non-Finite Value Rejection.

Verification evidence for the change to the validated clinical algorithm in
domain/services/artifact_rejector.py (PhysiologicalBoundsChecker scalar path
and the _require_finite array guard). This file adds NO further changes to
domain/ — it is a pure evidence lock around that fix.

THE FAILURE MODE BEING GUARDED (pre-fix behavior):
  `NaN < low` and `NaN > high` are BOTH False under IEEE-754. The bounds
  checker's range comparison therefore returned (True, "") for a NaN scalar —
  reporting it as "within physiological bounds". Because
  NEWS2Calculator._extract_value() and _assert_required_parameters_present()
  filter ONLY on ProcessedVitalSign.is_within_physiological_bounds, a NaN
  reading from a disconnected lead or a malformed OBX-5 would have been
  selected as the most-recent valid sample and carried into NEWS2 scoring,
  where every comparison band also evaluates False — silently yielding a
  component score of 0 (the "healthiest" band) for a parameter whose true
  value was unknown. That is a NEWS2 UNDER-estimate on corrupt input: the
  exact direction ISO 14971 HAZARD-NEWS2-003 exists to prevent.

WHAT THIS FILE PROVES:
  1. NaN is rejected for EVERY VitalSignType, with a populated note.
  2. ±Inf is rejected for every type that has configured physiological
     bounds, with a populated note.
  3. A NaN sample is excluded from NEWS2 input by the real pipeline.
  4. NEWS2InsufficientDataError is raised when a required parameter is
     present but NaN-only — fail-fast, not partial scoring.
  5. None fails LOUD (TypeError) rather than silently reporting in-bounds.

RESIDUAL FINDING (documented, not silently accepted — see
TestConsciousnessInfIsInertNotRejected below): CONSCIOUSNESS is the one
VitalSignType with no entry in _PHYSIOLOGICAL_BOUNDS, so ±Inf in its `value`
field returns (True, "") via the "no bounds configured" early return. This is
clinically inert rather than dangerous — _score_consciousness() reads
avpu_level, never value, and VitalSignSample.__post_init__ makes a
CONSCIOUSNESS sample without avpu_level unconstructable — but it is asserted
explicitly here so the behavior is recorded evidence rather than an untested
assumption, and so any future change that starts reading CONSCIOUSNESS.value
numerically breaks this test loudly.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest
from domain.entities.patient_context import PatientContext, SpO2Scale
from domain.entities.vital_sign import (
    AVPULevel,
    VitalSignSample,
    VitalSignType,
    VitalSignUnit,
)
from domain.services.artifact_rejector import (
    _PHYSIOLOGICAL_BOUNDS,
    PhysiologicalBoundsChecker,
)
from domain.services.news2_calculator import (
    NEWS2Calculator,
    NEWS2InsufficientDataError,
)
from domain.services.signal_processor import VitalSignProcessor

_UTC = timezone.utc
_T0 = datetime(2026, 8, 21, 12, 0, 0, tzinfo=_UTC)

# Every type that HAS configured physiological bounds. Derived from the
# production table rather than hardcoded, so adding a bounded type to
# artifact_rejector.py automatically extends this evidence.
_BOUNDED_TYPES = sorted(_PHYSIOLOGICAL_BOUNDS.keys(), key=lambda t: t.value)

# Units that satisfy VitalSignSample's construction contract per type.
_UNIT_FOR: dict[VitalSignType, VitalSignUnit] = {
    VitalSignType.HEART_RATE: VitalSignUnit.BPM,
    VitalSignType.RESPIRATORY_RATE: VitalSignUnit.BREATHS_PER_MIN,
    VitalSignType.SPO2: VitalSignUnit.PERCENT,
    VitalSignType.SYSTOLIC_BP: VitalSignUnit.MMHG,
    VitalSignType.DIASTOLIC_BP: VitalSignUnit.MMHG,
    VitalSignType.TEMPERATURE_CELSIUS: VitalSignUnit.CELSIUS,
    VitalSignType.CONSCIOUSNESS: VitalSignUnit.AVPU_SCALE,
    VitalSignType.SUPPLEMENTAL_O2: VitalSignUnit.BOOLEAN,
}


def _sample(
    vital_type: VitalSignType,
    value: float,
    *,
    offset_s: int = 0,
) -> VitalSignSample:
    """Build a minimal, construction-valid sample of the requested type."""
    return VitalSignSample(
        vital_sign_type=vital_type,
        value=value,
        unit=_UNIT_FOR[vital_type],
        timestamp=_T0 + timedelta(seconds=offset_s),
        avpu_level=(
            AVPULevel.ALERT if vital_type is VitalSignType.CONSCIOUSNESS else None
        ),
    )


def _healthy_vitals() -> list[VitalSignSample]:
    """A complete, all-normal set of the five NEWS2-mandatory parameters."""
    return [
        _sample(VitalSignType.RESPIRATORY_RATE, 16.0),
        _sample(VitalSignType.SPO2, 98.0),
        _sample(VitalSignType.SYSTOLIC_BP, 120.0),
        _sample(VitalSignType.HEART_RATE, 72.0),
        _sample(VitalSignType.TEMPERATURE_CELSIUS, 37.0),
    ]


class TestNaNRejectedForEveryVitalSignType:
    """
    HAZARD-DSP-007 core claim: NaN is never reported as in-bounds, for ANY
    type — including types with no configured bounds, since a NaN scalar is
    a data-corruption signal independent of physiological range.
    """

    @pytest.mark.parametrize("vital_type", list(VitalSignType), ids=lambda t: t.name)
    def test_nan_is_rejected_with_a_populated_note(
        self, vital_type: VitalSignType
    ) -> None:
        ok, note = PhysiologicalBoundsChecker().check(vital_type, float("nan"))

        assert ok is False, (
            f"{vital_type.name}: NaN reported as within physiological bounds. "
            "This is the exact HAZARD-DSP-007 failure mode — a NaN passing "
            "this flag reaches NEWS2 scoring and silently scores 0."
        )
        assert note, (
            f"{vital_type.name}: NaN rejected but with an empty note. The "
            "note is the audit-trail record of WHY the sample was excluded "
            "(surfaced via ProcessedVitalSign.pipeline_notes)."
        )
        assert "NaN" in note

    def test_every_vital_sign_type_is_covered_by_this_evidence(self) -> None:
        """
        Guard against a new VitalSignType being added to the enum without
        HAZARD-DSP-007 evidence extending to cover it.
        """
        checked = {
            t
            for t in VitalSignType
            if PhysiologicalBoundsChecker().check(t, float("nan"))[0] is False
        }
        assert checked == set(VitalSignType), (
            "A VitalSignType exists that does NOT reject NaN: "
            f"{set(VitalSignType) - checked}"
        )


class TestInfRejectedForEveryBoundedType:
    """
    +Inf/-Inf were already rejected pre-fix (Inf > high is True, unlike NaN),
    but that behavior was never asserted. Locking it here so a future change
    to the comparison order cannot silently regress it.
    """

    @pytest.mark.parametrize("vital_type", _BOUNDED_TYPES, ids=lambda t: t.name)
    @pytest.mark.parametrize("value", [math.inf, -math.inf], ids=["+inf", "-inf"])
    def test_infinite_value_is_rejected_with_a_populated_note(
        self, vital_type: VitalSignType, value: float
    ) -> None:
        ok, note = PhysiologicalBoundsChecker().check(vital_type, value)

        assert ok is False, f"{vital_type.name}: {value} reported as in-bounds."
        assert note, f"{vital_type.name}: {value} rejected with an empty note."
        assert "outside physiological range" in note


class TestConsciousnessInfIsInertNotRejected:
    """
    RESIDUAL FINDING, asserted explicitly rather than left untested.

    CONSCIOUSNESS has no _PHYSIOLOGICAL_BOUNDS entry, so ±Inf in `value`
    returns (True, "") via the "no bounds configured" early return. Recorded
    here as known-and-inert, with the reason it does not reach scoring.
    """

    @pytest.mark.parametrize("value", [math.inf, -math.inf], ids=["+inf", "-inf"])
    def test_inf_is_accepted_because_consciousness_has_no_numeric_bounds(
        self, value: float
    ) -> None:
        assert VitalSignType.CONSCIOUSNESS not in _PHYSIOLOGICAL_BOUNDS

        ok, _ = PhysiologicalBoundsChecker().check(VitalSignType.CONSCIOUSNESS, value)
        assert ok is True, (
            "Behavior changed: CONSCIOUSNESS now rejects Inf. That is a "
            "safe direction, but this evidence file documented the opposite "
            "— update the HAZARD-DSP-007 residual-finding note."
        )

    def test_consciousness_scoring_reads_avpu_not_value(self) -> None:
        """
        Proof the accepted Inf above is clinically inert: an Inf-valued
        CONSCIOUSNESS sample carrying AVPU=ALERT still scores 0, and the same
        sample carrying AVPU=NEW_CONFUSION still scores 3 (RCP 2017: any
        deviation from Alert scores 3). The numeric `value` never
        participates.
        """
        processor = VitalSignProcessor()
        context = PatientContext(patient_id="PT-DSP007", spo2_scale=SpO2Scale.SCALE_1)

        for avpu, expected in ((AVPULevel.ALERT, 0), (AVPULevel.NEW_CONFUSION, 3)):
            consciousness = VitalSignSample(
                vital_sign_type=VitalSignType.CONSCIOUSNESS,
                value=math.inf,
                unit=VitalSignUnit.AVPU_SCALE,
                timestamp=_T0,
                avpu_level=avpu,
            )
            processed = [
                processor.process(s) for s in (*_healthy_vitals(), consciousness)
            ]
            score = NEWS2Calculator().calculate(processed, context)

            assert score.consciousness_score == expected, (
                f"AVPU={avpu.name} with value=inf scored "
                f"{score.consciousness_score}, expected {expected}. The "
                "numeric value must never influence consciousness scoring."
            )


class TestNoneFailsLoudRatherThanSilently:
    """
    A None value (e.g. a malformed OBX-5 that an adapter failed to coerce)
    must not silently report in-bounds. It currently raises TypeError from
    math.isnan — a fail-loud outcome. Asserted so that a future "defensive"
    change to swallow it into (True, "") is caught here.
    """

    @pytest.mark.parametrize("vital_type", list(VitalSignType), ids=lambda t: t.name)
    def test_none_raises_rather_than_reporting_in_bounds(
        self, vital_type: VitalSignType
    ) -> None:
        with pytest.raises(TypeError):
            PhysiologicalBoundsChecker().check(vital_type, None)  # type: ignore[arg-type]


class TestNaNExcludedFromNEWS2Input:
    """
    End-to-end through the REAL pipeline (VitalSignProcessor ->
    NEWS2Calculator), not the bounds checker in isolation. This is the claim
    that actually matters clinically.
    """

    def test_nan_sample_is_flagged_out_of_bounds_by_the_processor(self) -> None:
        processed = VitalSignProcessor().process(
            _sample(VitalSignType.HEART_RATE, float("nan"))
        )

        assert processed.is_within_physiological_bounds is False
        assert any("NaN" in n for n in processed.pipeline_notes), (
            "NaN rejection is not recorded in pipeline_notes — the audit "
            "trail would not explain why the sample was dropped."
        )

    def test_a_more_recent_nan_does_not_displace_an_earlier_valid_reading(
        self,
    ) -> None:
        """
        The highest-value guard in this file.

        _extract_value() takes the MOST RECENT within-bounds sample. If NaN
        were treated as in-bounds, a NaN arriving after a valid reading would
        win the max(timestamp) selection and become the scored value. Here a
        valid HR of 130 (score 2) is followed by a NaN; the score must still
        reflect 130, not degrade to the NaN-induced 0.
        """
        processor = VitalSignProcessor()
        context = PatientContext(patient_id="PT-DSP007", spo2_scale=SpO2Scale.SCALE_1)

        vitals = [
            v
            for v in _healthy_vitals()
            if v.vital_sign_type is not VitalSignType.HEART_RATE
        ]
        vitals.append(_sample(VitalSignType.HEART_RATE, 130.0, offset_s=0))
        vitals.append(_sample(VitalSignType.HEART_RATE, float("nan"), offset_s=60))

        score = NEWS2Calculator().calculate(
            [processor.process(s) for s in vitals], context
        )

        assert score.heart_rate_score == 2, (
            "A NaN heart-rate sample arriving after a valid 130 bpm reading "
            "displaced it in _extract_value()'s most-recent selection. "
            "HAZARD-DSP-007: this is a NEWS2 under-estimate on corrupt input."
        )


class TestNaNOnlyRequiredParameterRaisesInsufficientData:
    """
    IEC 62304 REQ-NEWS2-003 / ISO 14971 HAZARD-NEWS2-003: fail fast rather
    than score partially. If a mandatory parameter's ONLY sample is NaN, the
    parameter is effectively absent and must raise.
    """

    @pytest.mark.parametrize(
        "missing_type",
        [
            VitalSignType.RESPIRATORY_RATE,
            VitalSignType.SPO2,
            VitalSignType.SYSTOLIC_BP,
            VitalSignType.HEART_RATE,
            VitalSignType.TEMPERATURE_CELSIUS,
        ],
        ids=lambda t: t.name,
    )
    def test_nan_only_mandatory_parameter_raises(
        self, missing_type: VitalSignType
    ) -> None:
        processor = VitalSignProcessor()
        context = PatientContext(patient_id="PT-DSP007", spo2_scale=SpO2Scale.SCALE_1)

        vitals = [v for v in _healthy_vitals() if v.vital_sign_type is not missing_type]
        vitals.append(_sample(missing_type, float("nan")))

        with pytest.raises(NEWS2InsufficientDataError) as exc:
            NEWS2Calculator().calculate([processor.process(s) for s in vitals], context)

        assert missing_type.name in str(exc.value), (
            "The raised error does not name the NaN-only parameter, so a "
            "clinician/integrator cannot tell which input was rejected."
        )

    def test_all_mandatory_parameters_nan_raises_naming_all_of_them(self) -> None:
        processor = VitalSignProcessor()
        context = PatientContext(patient_id="PT-DSP007", spo2_scale=SpO2Scale.SCALE_1)

        vitals = [_sample(v.vital_sign_type, float("nan")) for v in _healthy_vitals()]

        with pytest.raises(NEWS2InsufficientDataError) as exc:
            NEWS2Calculator().calculate([processor.process(s) for s in vitals], context)

        message = str(exc.value)
        for vital_type in _healthy_vitals():
            assert vital_type.vital_sign_type.name in message

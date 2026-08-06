"""
Integration Tests — HL7 v2.x Waveform → DSP Pipeline → NEWS2, End-to-End.

Closes the P0 gap identified in Phase 5 review: prior to this revision, the
HL7v2Adapter discarded NA/ED (waveform) OBX segments, so the notch/bandpass/
Hampel DSP pipeline in domain/services/signal_processor.py was never
exercised by data arriving via POST /api/v1/ingest (the primary bedside
monitor route) — confirmed at the time by 53% coverage on signal_processor.py
with the missing lines being exactly the waveform orchestration block.

This file proves the wiring is now real: a raw HL7 ORU^R01 message carrying
an NA waveform OBX is parsed, run through VitalsOrchestrator.analyse(), and
the resulting FHIR-bound data is checked for actual, numerically-verified
notch/bandpass attenuation — not just object-shape assertions.

IEC 62304 §5.7 / ISO 14971 HAZARD-DSP-001..004, HAZARD-PROTO-002, HAZARD-WAVE-001.

Design note recorded during construction of this test (documented here for
audit trail rather than silently discovered and left unmentioned): the
current Notch -> Bandpass -> Hampel execution order means a short-duration
injected artifact that survives notch filtering fine can be substantially
smoothed by the 0.5 Hz-cutoff Butterworth bandpass stage before Hampel ever
sees it, reducing Hampel's sensitivity to it in the full chain. This is
captured explicitly, not silently, in TestKnownArtifactDetectionLimitation
below via a strict xfail — see that class's docstring for detail. It is a
tracked, open risk-register item, not a defect introduced by this change and
not something this change attempts to silently fix (reordering pipeline
stages is a clinical-safety architecture decision requiring its own explicit
review, out of scope here).
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest
from domain.entities.news2_score import NEWS2RiskLevel
from domain.entities.patient_context import PatientContext, SpO2Scale
from domain.entities.vital_sign import VitalSignSample, VitalSignType, VitalSignUnit
from domain.services.artifact_rejector import (
    BandpassFilter,
    DualNotchFilter,
    HampelFilter,
)
from domain.services.signal_processor import _WAVEFORM_CAPABLE_TYPES, VitalSignProcessor
from domain.services.vitals_orchestrator import VitalsOrchestrator
from infrastructure.adapters.hl7v2_adapter import (
    _WAVEFORM_DEFAULT_SAMPLING_RATE_HZ,
    HL7v2Adapter,
)

_ADAPTER = HL7v2Adapter()
_ORCHESTRATOR = VitalsOrchestrator()

# ── Synthetic Waveform Construction ────────────────────────────────────────────
#
# 200 Hz, 2 s (400 samples): a 1.2 Hz "physiological" oscillation (representing
# a slow underlying trend on the ECG channel) plus 60 Hz mains interference.
# 200 Hz is DELIBERATELY different from the HR default sampling rate (250 Hz)
# and is supplied as an explicit OBX-6 numeric override, so this test exercises
# the override path, not just the default table.

_FS = 200.0
_N = 400
_T = np.linspace(0, 2.0, _N, endpoint=False)
_PURE_SIGNAL = 0.8 * np.sin(2 * np.pi * 1.2 * _T)
_INTERFERENCE = 0.5 * np.sin(2 * np.pi * 60.0 * _T)
_RAW_WAVEFORM = _PURE_SIGNAL + _INTERFERENCE


def _waveform_field(samples: np.ndarray) -> str:
    """Render a numpy array as an HL7 NA (caret-separated) OBX-5 value."""
    return "^".join(f"{v:.6f}" for v in samples)


def _build_waveform_oru(waveform: np.ndarray, sampling_rate_hz: float) -> str:
    """
    Build a raw HL7 v2.x ORU^R01 message with:
      - OBX-1: NA waveform for HEART_RATE (ECG-derived), OBX-6 = explicit
        numeric sampling-rate override.
      - OBX-2..6: scalar NM observations for all 5 mandatory NEWS2 parameters,
        chosen to be entirely within normal range (NEWS2 total = 0, NORMAL).

    This mirrors the real-world pattern already established by the pre-existing
    WAVEFORM_ORU fixture in test_hl7v2_adapter.py: a waveform channel plus a
    companion scalar NM OBX carrying the actual clinically-scored value.
    """
    ts = "20240115100000"
    return (
        f"MSH|^~\\&|DRAEGER|ICU-BED-12|EHR|HOSPITAL|{ts}||ORU^R01|MSGWAVE01|P|2.5.1\r"
        "PID|1||PT-WAVE-001^^^HOSP^MR\r"
        f"OBX|1|NA|8867-4^ECG Waveform^LN||{_waveform_field(waveform)}"
        f"|{sampling_rate_hz:g}||||F|||{ts}\r"
        f"OBX|2|NM|8867-4^Heart rate^LN||78|/min||||F|||{ts}\r"
        f"OBX|3|NM|9279-1^Respiratory rate^LN||16|/min||||F|||{ts}\r"
        f"OBX|4|NM|59408-5^SpO2^LN||98|%||||F|||{ts}\r"
        f"OBX|5|NM|8480-6^Systolic BP^LN||118|mmHg||||F|||{ts}\r"
        f"OBX|6|NM|8310-5^Temperature^LN||36.8|Cel||||F|||{ts}\r"
    )


class TestWaveformCapableTypeInvariant:
    """
    The HL7 adapter's waveform sampling-rate default table and the DSP
    pipeline's waveform-capable type set must never silently drift apart —
    otherwise the adapter could successfully parse a waveform for a type the
    DSP pipeline will never actually filter (or vice versa).
    """

    def test_waveform_capable_types_match_signal_processor(self) -> None:
        assert set(_WAVEFORM_DEFAULT_SAMPLING_RATE_HZ) == _WAVEFORM_CAPABLE_TYPES


class TestWaveformPipelineEndToEnd:
    """
    Full path: raw HL7 ORU^R01 (NA waveform + scalar OBXs) -> HL7v2Adapter
    -> VitalsOrchestrator -> DSP-cleaned waveform + NEWS2 score.
    """

    def test_hl7_parse_produces_waveform_and_scalar_samples(self) -> None:
        raw = _build_waveform_oru(_RAW_WAVEFORM, _FS)
        result = _ADAPTER.parse(raw)

        assert result.skipped_obx_count == 0
        assert result.patient_id == "PT-WAVE-001"

        waveform_samples = [
            s
            for s in result.samples
            if s.vital_sign_type is VitalSignType.HEART_RATE and s.waveform is not None
        ]
        scalar_hr_samples = [
            s
            for s in result.samples
            if s.vital_sign_type is VitalSignType.HEART_RATE and s.waveform is None
        ]
        assert len(waveform_samples) == 1
        assert len(scalar_hr_samples) == 1

        wave = waveform_samples[0]
        assert len(wave.waveform) == _N
        assert wave.sampling_rate_hz == _FS  # explicit OBX-6 override honored
        assert wave.value == 0.0  # documented placeholder, not a clinical reading
        assert scalar_hr_samples[0].value == 78.0

    def test_dsp_pipeline_runs_and_attenuates_interference(self) -> None:
        """
        Proves Finding 1 is closed: notch + bandpass genuinely execute against
        HL7-sourced waveform data and materially reduce 60 Hz interference,
        verified numerically (RMS distance to the known pure signal), not
        just via object-shape assertions.
        """
        raw = _build_waveform_oru(_RAW_WAVEFORM, _FS)
        result = _ADAPTER.parse(raw)
        analysis = _ORCHESTRATOR.analyse(
            samples=result.samples,
            context=PatientContext(patient_id="PT-WAVE-001", spo2_scale=SpO2Scale.SCALE_1),
        )

        wave_pv = next(
            pv
            for pv in analysis.processed_vitals
            if pv.original.waveform is not None
        )
        assert wave_pv.cleaned_waveform is not None
        assert len(wave_pv.cleaned_waveform) == _N

        notes_text = " | ".join(wave_pv.pipeline_notes)
        assert "[NOTCH]" in notes_text
        assert "[BANDPASS]" in notes_text
        assert "[HAMPEL]" in notes_text

        cleaned = np.array(wave_pv.cleaned_waveform, dtype=np.float64)
        raw_error = float(np.sqrt(np.mean((_RAW_WAVEFORM - _PURE_SIGNAL) ** 2)))
        cleaned_error = float(np.sqrt(np.mean((cleaned - _PURE_SIGNAL) ** 2)))

        assert cleaned_error < raw_error * 0.6, (
            f"Expected material attenuation of 60 Hz interference: "
            f"raw_error={raw_error:.4f}, cleaned_error={cleaned_error:.4f}. "
            "(Empirically observed ratio during development was ~0.32; 0.6 "
            "leaves margin so this is not a brittle exact-value assertion.)"
        )

    def test_dataset_wide_bounds_exclusion_flags_the_waveform_placeholder(self) -> None:
        """
        The waveform-only sample's placeholder scalar (0.0) must be flagged
        out-of-bounds by the PRE-EXISTING, unmodified PhysiologicalBoundsChecker
        — this is the mechanism that keeps it out of NEWS2 scoring. Confirms
        the pre-existing bounds-exclusion audit note fires as expected.
        """
        raw = _build_waveform_oru(_RAW_WAVEFORM, _FS)
        result = _ADAPTER.parse(raw)
        analysis = _ORCHESTRATOR.analyse(
            samples=result.samples,
            context=PatientContext(patient_id="PT-WAVE-001"),
        )

        wave_pv = next(
            pv for pv in analysis.processed_vitals if pv.original.waveform is not None
        )
        assert wave_pv.is_within_physiological_bounds is False

        warnings_text = " | ".join(analysis.pipeline_warnings)
        assert "[ARTIFACT]" in warnings_text
        assert "HEART_RATE" in warnings_text


class TestWaveformNeverFeedsNews2Score:
    """
    ISO 14971 HAZARD-BOUNDS-001 / HAZARD-NEWS2-003: the waveform-only
    placeholder sample must never be selectable as the NEWS2 scoring input
    for its vital sign type — the scalar companion NM OBX must always win.
    This is the regression guard referenced from hl7v2_adapter.py's
    _build_waveform_sample docstring.
    """

    def test_news2_score_reflects_only_scalar_values(self) -> None:
        raw = _build_waveform_oru(_RAW_WAVEFORM, _FS)
        result = _ADAPTER.parse(raw)
        analysis = _ORCHESTRATOR.analyse(
            samples=result.samples,
            context=PatientContext(patient_id="PT-WAVE-001"),
        )

        assert analysis.news2_score is not None
        assert analysis.news2_score.total == 0
        assert analysis.news2_score.risk_level is NEWS2RiskLevel.NORMAL
        assert analysis.news2_score.heart_rate_score == 0  # from scalar HR=78, not 0.0

    def test_abnormal_scalar_hr_still_scores_correctly_alongside_waveform(self) -> None:
        """
        Regression guard: an abnormal scalar HR (e.g. 135 -> score 3) must
        still be picked up correctly even though a HEART_RATE waveform sample
        with value=0.0 is present in the same sample set. If NEWS2Calculator
        ever changed to pick the wrong (most-recent-by-timestamp, ignoring
        bounds) candidate, this test would catch it.
        """
        ts = "20240115100000"
        raw = (
            f"MSH|^~\\&|DRAEGER|ICU-BED-12|EHR|HOSPITAL|{ts}||ORU^R01|MSGWAVE02|P|2.5.1\r"
            "PID|1||PT-WAVE-002\r"
            f"OBX|1|NA|8867-4^ECG Waveform^LN||{_waveform_field(_RAW_WAVEFORM)}"
            f"|{_FS:g}||||F|||{ts}\r"
            f"OBX|2|NM|8867-4^Heart rate^LN||135|/min||||F|||{ts}\r"
            f"OBX|3|NM|9279-1^Respiratory rate^LN||16|/min||||F|||{ts}\r"
            f"OBX|4|NM|59408-5^SpO2^LN||98|%||||F|||{ts}\r"
            f"OBX|5|NM|8480-6^Systolic BP^LN||118|mmHg||||F|||{ts}\r"
            f"OBX|6|NM|8310-5^Temperature^LN||36.8|Cel||||F|||{ts}\r"
        )
        result = _ADAPTER.parse(raw)
        analysis = _ORCHESTRATOR.analyse(
            samples=result.samples,
            context=PatientContext(patient_id="PT-WAVE-002"),
        )
        assert analysis.news2_score is not None
        assert analysis.news2_score.heart_rate_score == 3  # HR=135 -> >=131 band


class TestKnownArtifactDetectionLimitation:
    """
    Documented, tracked, NOT-yet-mitigated finding from constructing this
    integration test (recorded here rather than silently discovered and left
    unreported).

    Empirically, in the current Notch -> Bandpass -> Hampel execution order
    (signal_processor.py, unmodified by this change), a short-duration
    injected artifact large enough to be trivially detected by HampelFilter
    immediately after the notch stage becomes UNDETECTABLE by the same
    HampelFilter once the 0.5 Hz-cutoff / order-3 Butterworth bandpass stage
    has also run — the bandpass filter's impulse response is long enough,
    relative to Hampel's local window (radius=5), to smear the artifact's
    local statistical signature below Hampel's detection threshold, even at
    100x the surrounding signal amplitude.

    This is marked xfail(strict=True): it asserts the DESIRED behavior
    (artifact detected end-to-end). It is expected to fail today. If a future
    change to filter ordering or Hampel windowing makes it pass, pytest will
    report XPASS and fail the suite (strict=True) — forcing an explicit,
    conscious update to this marker and the risk register, rather than a
    silent, unnoticed improvement (or regression) in either direction.

    This is a candidate ISO 14971 risk-register entry (proposed ID
    HAZARD-DSP-005) for the product/clinical-safety owner to review. It is
    NOT altered or worked around by this change, per the instruction to keep
    the DSP safety path — including its current, already-validated ordering —
    strictly intact.
    """

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "KNOWN OPEN RISK (see class docstring): bandpass smoothing "
            "reduces Hampel's sensitivity to short-duration artifacts in the "
            "current Notch->Bandpass->Hampel order. Do not remove this "
            "marker without a documented mitigation and risk-register update."
        ),
    )
    def test_hampel_detects_injected_artifact_after_full_dsp_chain(self) -> None:
        """
        NOTE: outlier_count alone is NOT a valid proxy here — this exact
        filter chain also produces 2 artifact-independent flagged samples at
        the tail of every processed array (a filtfilt edge/padding effect,
        reproducible regardless of any injected artifact; see the module
        docstring's second finding). So this test replicates the identical
        Notch -> Bandpass -> Hampel sequence used by
        domain.services.signal_processor.VitalSignProcessor.process()
        directly, to inspect the outlier MASK near the injected index
        specifically, rather than relying on the aggregate count.
        """
        artifact_index = 150
        waveform = _RAW_WAVEFORM.copy()
        waveform[artifact_index] += 5.0

        notched = DualNotchFilter().apply(waveform, _FS)
        bandpassed = BandpassFilter(vital_sign_type=VitalSignType.HEART_RATE).apply(
            notched, _FS
        )
        _, mask = HampelFilter().apply_with_mask(bandpassed)

        assert bool(np.any(mask[artifact_index - 2 : artifact_index + 3])), (
            "Desired: the injected artifact at index "
            f"{artifact_index} is caught by Hampel even after bandpass "
            "smoothing. Currently false — see class docstring."
        )

    def test_hampel_alone_does_detect_the_same_artifact_pre_bandpass(self) -> None:
        """
        Confirms HampelFilter itself is not at fault in isolation — it does
        detect this exact injected artifact when applied directly after
        notch filtering (i.e., without the intervening bandpass stage).
        This isolates the limitation above to the specific stage ordering,
        not to a defect in HampelFilter's own algorithm (which remains
        correctly covered by its dedicated unit tests in
        tests/unit/test_artifact_rejector.py).
        """
        artifact_index = 150
        waveform = _RAW_WAVEFORM.copy()
        waveform[artifact_index] += 5.0

        notched = DualNotchFilter().apply(waveform, _FS)
        _, mask = HampelFilter().apply_with_mask(notched)

        assert bool(np.any(mask[artifact_index - 2 : artifact_index + 3])), (
            "HampelFilter must detect the injected artifact when run "
            "directly after notch filtering (pre-bandpass)."
        )


def _waveform_sample(
    waveform: np.ndarray, sampling_rate_hz: float
) -> VitalSignSample:
    """Minimal HEART_RATE waveform sample for direct VitalSignProcessor calls."""
    return VitalSignSample(
        vital_sign_type=VitalSignType.HEART_RATE,
        value=0.0,
        unit=VitalSignUnit.BPM,
        timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
        waveform=tuple(float(v) for v in waveform),
        sampling_rate_hz=sampling_rate_hz,
    )


class TestHazardDsp006EdgeMitigation:
    """
    ISO 14971 HAZARD-DSP-006: filtfilt boundary-transient samples at the tail
    of every bandpass-filtered array must not be reported as motion artifacts
    (see class docstring on TestKnownArtifactDetectionLimitation for the raw
    reproduction). VitalSignProcessor.process() reclassifies them via
    BandpassFilter.edge_margin_samples() into a distinct [HAMPEL-EDGE] note,
    excluded from outlier_count, WITHOUT altering cleaned_waveform values.
    """

    def test_clean_waveform_reports_zero_outliers_despite_raw_tail_flags(self) -> None:
        """
        Confirms the raw Notch->Bandpass->Hampel chain (bypassing
        VitalSignProcessor) DOES flag artifact-independent tail samples for
        this exact fixture — establishing there is something to mitigate —
        then confirms VitalSignProcessor.process() reclassifies them out of
        outlier_count and surfaces the dedicated audit note instead.
        """
        notched = DualNotchFilter().apply(_RAW_WAVEFORM, _FS)
        bandpassed = BandpassFilter(vital_sign_type=VitalSignType.HEART_RATE).apply(
            notched, _FS
        )
        _, raw_mask = HampelFilter().apply_with_mask(bandpassed)
        assert bool(np.any(raw_mask)), (
            "Precondition: this fixture must reproduce the raw filtfilt "
            "edge-flag artifact-independently, or this test proves nothing."
        )

        sample = _waveform_sample(_RAW_WAVEFORM, _FS)
        processed = VitalSignProcessor().process(sample)

        assert processed.outlier_count == 0, (
            "No genuine motion artifact was injected — outlier_count must "
            "be 0 once filtfilt edge-transient samples are excluded from "
            "motion-artifact classification. HAZARD-DSP-006."
        )
        notes_text = " | ".join(processed.pipeline_notes)
        assert "[HAMPEL-EDGE]" in notes_text
        assert "No motion artifacts detected" in notes_text

    def test_edge_zone_samples_still_corrected_in_cleaned_waveform(self) -> None:
        """
        The reclassification is audit/reporting-only: the numeric values of
        edge-zone samples flagged by Hampel are still median-replaced in
        cleaned_waveform, identically to core-zone flagged samples. This
        proves HAZARD-DSP-006 mitigation does not touch filter numerics.
        """
        sample = _waveform_sample(_RAW_WAVEFORM, _FS)
        processed = VitalSignProcessor().process(sample)

        notched = DualNotchFilter().apply(_RAW_WAVEFORM, _FS)
        bandpassed = BandpassFilter(vital_sign_type=VitalSignType.HEART_RATE).apply(
            notched, _FS
        )
        expected_cleaned, raw_mask = HampelFilter().apply_with_mask(bandpassed)
        flagged_indices = np.where(raw_mask)[0]
        assert len(flagged_indices) > 0  # precondition from the prior test

        cleaned = np.array(processed.cleaned_waveform, dtype=np.float64)
        for idx in flagged_indices:
            assert cleaned[idx] == pytest.approx(expected_cleaned[idx]), (
                f"Edge-zone sample at index {idx} must still be median-"
                "corrected identically to the raw Hampel output — only its "
                "motion-artifact classification changes, never its value."
            )

    def test_known_limitation_real_artifact_inside_edge_margin_is_undercounted(
        self,
    ) -> None:
        """
        DOCUMENTED, ACCEPTED TRADE-OFF (see signal_processor.py Stage 4
        comment): a genuine motion artifact that happens to land inside the
        edge margin is indistinguishable, using only local Hampel
        statistics, from filtfilt boundary ringing. It is still corrected
        in cleaned_waveform but is EXCLUDED from outlier_count and the
        [HAMPEL] note — i.e. under-reported as a motion artifact. This test
        exists to make that limitation explicit and regression-guarded,
        not to assert it is safe in all contexts. Re-escalate if any future
        feature relies on outlier_count as a complete motion-artifact audit
        trail for edge-adjacent samples.
        """
        bp = BandpassFilter(vital_sign_type=VitalSignType.HEART_RATE)
        margin = bp.edge_margin_samples(_FS)
        assert margin > 0  # precondition: HR at 200 Hz has a non-trivial margin

        artifact_index = _N - 1  # last sample -- guaranteed inside the edge margin
        waveform = _RAW_WAVEFORM.copy()
        waveform[artifact_index] += 5.0  # large, unambiguous spike

        sample = _waveform_sample(waveform, _FS)
        processed = VitalSignProcessor().process(sample)

        notes_text = " | ".join(processed.pipeline_notes)
        assert "[HAMPEL-EDGE]" in notes_text, (
            "The injected artifact must fall within the reported edge zone "
            "for this test to demonstrate the intended trade-off."
        )
        assert "No motion artifacts detected" in notes_text or (
            processed.outlier_count == 0
        ), (
            "KNOWN LIMITATION: an artifact inside the edge margin is not "
            "counted as a motion artifact by outlier_count/[HAMPEL] — "
            "documented trade-off, not a defect. If this assertion starts "
            "failing, the trade-off's boundary has shifted and the risk "
            "register / clinical-safety owner must be informed either way."
        )

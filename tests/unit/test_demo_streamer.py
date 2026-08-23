"""
Unit tests — scripts/demo_inject.py continuous three-bed narrative (Phase 5).

These tests exist to prove three things about the DEMONSTRATION data
generator, none of which may be taken on trust in a clinical demo:

  1. Every OBX-3 code the streamer emits already resolves through the
     adapter's existing _LOINC_TO_TYPE / _VENDOR_TO_TYPE tables --
     skipped_obx_count == 0 for every bed, every stage. The adapter was NOT
     edited to accommodate this script (HARD CONSTRAINT: mapping tables are
     append-only and were not touched at all here); if a code were unmapped,
     the message would silently lose that vital sign and the demo would show
     an incomplete score.

  2. BED-03's scripted sepsis ramp produces a monotonically non-decreasing
     NEWS2 trajectory that actually visits NORMAL, LOW, MEDIUM and HIGH, as
     scored by the REAL validated NEWS2Calculator -- not by expectations
     hardcoded in this file. A demo that claims "watch it climb through the
     bands" must actually do so.

  3. Seeding is reproducible: the same --seed yields byte-identical
     messages, so a demo can be rehearsed and replayed exactly.

The streamer performs no clinical computation of its own. These tests drive
its output through the same domain pipeline the gateway uses
(HL7v2Adapter -> VitalSignProcessor -> NEWS2Calculator) so what is asserted
here is what the gateway would actually produce.
"""

from __future__ import annotations

import importlib.util
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import pytest
from domain.entities.news2_score import NEWS2RiskLevel
from domain.entities.patient_context import PatientContext, SpO2Scale
from domain.services.news2_calculator import NEWS2Calculator
from domain.services.signal_processor import VitalSignProcessor
from infrastructure.adapters.hl7v2_adapter import HL7v2Adapter

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STREAMER_PATH = _REPO_ROOT / "scripts" / "demo_inject.py"
_FIXED_MOMENT = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)


def _load_streamer() -> ModuleType:
    """
    Import scripts/demo_inject.py by path.

    scripts/ is deliberately outside the importable src/ package tree (it is
    excluded from the production image via .dockerignore), so it cannot be
    imported normally. Loading by path keeps that separation intact rather
    than adding scripts/ to the package path just for tests.
    """
    spec = importlib.util.spec_from_file_location("demo_inject", _STREAMER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec_module: @dataclass resolves field types via
    # sys.modules[cls.__module__], which raises AttributeError if the module
    # being defined is not yet registered.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


streamer = _load_streamer()


def _score(hl7_message: str, spo2_scale: SpO2Scale):
    """Drive one raw HL7 message through the real pipeline and return the score."""
    parse_result = HL7v2Adapter().parse(hl7_message)
    processor = VitalSignProcessor()
    processed = [processor.process(s) for s in parse_result.samples]
    context = PatientContext(patient_id=parse_result.patient_id, spo2_scale=spo2_scale)
    return parse_result, NEWS2Calculator().calculate(processed, context)


class TestEveryEmittedObxCodeIsAlreadyMapped:
    """
    Claim 1: no OBX segment the streamer emits is ever skipped by the
    adapter. A skipped OBX is a silently missing vital sign.
    """

    @pytest.mark.parametrize("profile", streamer.BED_PROFILES, ids=lambda p: p.bed_id)
    def test_no_obx_is_skipped_for_any_stage_of_any_bed(self, profile) -> None:
        rng = random.Random(f"7:{profile.bed_id}")

        # Sample across a full sepsis loop so BED-03's every stage is covered,
        # and across many ticks so BED-01/02's seeded drift is covered too.
        for tick in range(50):
            elapsed = tick * (streamer.SEPSIS_LOOP_SECONDS / 50.0)
            _, vitals = streamer.vitals_for_bed(profile, tick, elapsed, rng)
            message = streamer.build_oru_r01(
                profile, vitals, tick, moment=_FIXED_MOMENT
            )
            parse_result = HL7v2Adapter().parse(message)

            assert parse_result.skipped_obx_count == 0, (
                f"{profile.bed_id} tick {tick}: adapter skipped "
                f"{parse_result.skipped_obx_count} OBX segment(s). "
                f"Warnings: {parse_result.warnings}"
            )

    @pytest.mark.parametrize("profile", streamer.BED_PROFILES, ids=lambda p: p.bed_id)
    def test_all_seven_news2_parameters_are_present(self, profile) -> None:
        """
        All seven NEWS2 parameters must arrive, or the calculator would raise
        NEWS2InsufficientDataError and the bed would show no score at all.
        """
        rng = random.Random(f"7:{profile.bed_id}")
        _, vitals = streamer.vitals_for_bed(profile, 0, 0.0, rng)
        message = streamer.build_oru_r01(profile, vitals, 0, moment=_FIXED_MOMENT)
        parse_result = HL7v2Adapter().parse(message)

        present = {s.vital_sign_type for s in parse_result.samples}
        assert len(present) == 7, f"{profile.bed_id}: only got {present}"

    @pytest.mark.parametrize("profile", streamer.BED_PROFILES, ids=lambda p: p.bed_id)
    def test_msh3_resolves_to_the_intended_vendor(self, profile) -> None:
        """The three-vendor story requires the adapter to actually detect three vendors."""
        rng = random.Random(f"7:{profile.bed_id}")
        _, vitals = streamer.vitals_for_bed(profile, 0, 0.0, rng)
        message = streamer.build_oru_r01(profile, vitals, 0, moment=_FIXED_MOMENT)
        parse_result = HL7v2Adapter().parse(message)

        assert (
            parse_result.detected_vendor.value
            in profile.vendor_label.upper().replace(" ", "_")
            or parse_result.detected_vendor.value in profile.sending_application
        ), (
            f"{profile.bed_id}: MSH-3 {profile.sending_application!r} resolved to "
            f"{parse_result.detected_vendor.value!r}"
        )

    def test_the_three_beds_resolve_to_three_distinct_vendors(self) -> None:
        vendors = set()
        for profile in streamer.BED_PROFILES:
            rng = random.Random(f"7:{profile.bed_id}")
            _, vitals = streamer.vitals_for_bed(profile, 0, 0.0, rng)
            message = streamer.build_oru_r01(profile, vitals, 0, moment=_FIXED_MOMENT)
            vendors.add(HL7v2Adapter().parse(message).detected_vendor)

        assert len(vendors) == 3, (
            "The demo's core claim is one adapter normalising THREE vendor "
            f"vocabularies, but only {len(vendors)} distinct vendor(s) were "
            f"detected: {vendors}"
        )


class TestSepsisRampTrajectory:
    """
    Claim 2: BED-03 climbs monotonically and visits every risk band, as
    scored by the real calculator.
    """

    @staticmethod
    def _bed03():
        return next(p for p in streamer.BED_PROFILES if p.bed_id == "ICU-BED-03")

    def _trajectory(self) -> list[tuple[str, int, NEWS2RiskLevel]]:
        profile = self._bed03()
        rng = random.Random("unused-bed03-is-deterministic")
        seen: list[tuple[str, int, NEWS2RiskLevel]] = []
        for step in range(40):
            elapsed = step * (streamer.SEPSIS_LOOP_SECONDS / 40.0)
            stage, vitals = streamer.vitals_for_bed(profile, step, elapsed, rng)
            message = streamer.build_oru_r01(
                profile, vitals, step, moment=_FIXED_MOMENT
            )
            _, score = _score(message, SpO2Scale.SCALE_1)
            seen.append((stage, score.total, score.risk_level))
        return seen

    def test_trajectory_is_monotonically_non_decreasing(self) -> None:
        trajectory = self._trajectory()
        totals = [total for _, total, _ in trajectory]

        for index in range(1, len(totals)):
            assert totals[index] >= totals[index - 1], (
                "Sepsis ramp NEWS2 total decreased mid-deterioration at step "
                f"{index}: {totals[index - 1]} -> {totals[index]}. Full "
                f"trajectory: {totals}"
            )

    def test_trajectory_visits_normal_low_medium_and_high(self) -> None:
        levels = [level for _, _, level in self._trajectory()]

        for expected in (
            NEWS2RiskLevel.NORMAL,
            NEWS2RiskLevel.LOW,
            NEWS2RiskLevel.MEDIUM,
            NEWS2RiskLevel.HIGH,
        ):
            assert expected in levels, (
                f"Sepsis ramp never reached {expected.value}. The demo "
                "narrates NORMAL -> LOW -> MEDIUM -> HIGH; a band that never "
                f"appears makes that narration false. Saw: "
                f"{[level.value for level in levels]}"
            )

    def test_trajectory_starts_normal_and_ends_high(self) -> None:
        trajectory = self._trajectory()
        assert trajectory[0][2] is NEWS2RiskLevel.NORMAL
        assert trajectory[-1][2] is NEWS2RiskLevel.HIGH

    def test_climax_stage_carries_new_confusion(self) -> None:
        """
        RCP 2017: any deviation from Alert scores 3. The climax is narrated
        as "new confusion", so AVPU must actually be C at that point.
        """
        _, vitals = streamer.sepsis_stage_at(0.95)
        assert vitals.avpu == "C"

    def test_stage_lookup_is_step_and_hold_not_interpolated(self) -> None:
        """
        Each band must be HELD long enough to read on screen. Interpolation
        would sweep through MEDIUM in a frame or two.
        """
        first = streamer.sepsis_stage_at(0.50)
        second = streamer.sepsis_stage_at(0.60)
        assert first == second, "Stage changed within a single hold window."

    def test_ramp_loops_so_the_demo_can_repeat(self) -> None:
        assert streamer.sepsis_stage_at(0.10) == streamer.sepsis_stage_at(1.10)


class TestSpo2ScaleContrast:
    """
    BED-02's commercial moment: the same reading scores differently on
    Scale 1 vs Scale 2. Verified through the real calculator.
    """

    @staticmethod
    def _bed02():
        return next(p for p in streamer.BED_PROFILES if p.bed_id == "ICU-BED-02")

    def test_scale_2_scores_lower_than_scale_1_for_the_same_message(self) -> None:
        profile = self._bed02()
        rng = random.Random(f"42:{profile.bed_id}")
        _, vitals = streamer.vitals_for_bed(profile, 0, 0.0, rng)
        message = streamer.build_oru_r01(profile, vitals, 0, moment=_FIXED_MOMENT)

        _, scale_1 = _score(message, SpO2Scale.SCALE_1)
        _, scale_2 = _score(message, SpO2Scale.SCALE_2)

        assert scale_2.total < scale_1.total, (
            "The COPD bed scores the same or higher on Scale 2 than Scale 1, "
            "so the demo's Scale 1/Scale 2 contrast would show nothing. "
            f"Scale 1={scale_1.total}, Scale 2={scale_2.total}"
        )
        assert scale_1.spo2_score > scale_2.spo2_score

    def test_spo2_stays_inside_the_copd_target_band(self) -> None:
        """
        88-92% is the band that makes the contrast clinically meaningful.
        Seeded drift must not wander outside it.
        """
        profile = self._bed02()
        rng = random.Random(f"42:{profile.bed_id}")
        for tick in range(100):
            _, vitals = streamer.vitals_for_bed(profile, tick, tick * 2.0, rng)
            assert (
                88.0 <= vitals.spo2 <= 92.0
            ), f"tick {tick}: SpO2 {vitals.spo2} left the 88-92% COPD band"

    def test_bed_02_is_always_on_supplemental_oxygen(self) -> None:
        profile = self._bed02()
        rng = random.Random(f"42:{profile.bed_id}")
        for tick in range(20):
            _, vitals = streamer.vitals_for_bed(profile, tick, tick * 2.0, rng)
            assert vitals.on_supplemental_o2 is True


class TestSeedingIsReproducible:
    """Claim 3: a rehearsed demo replays identically."""

    @pytest.mark.parametrize("profile", streamer.BED_PROFILES, ids=lambda p: p.bed_id)
    def test_same_seed_yields_identical_messages(self, profile) -> None:
        def run() -> list[str]:
            rng = random.Random(f"42:{profile.bed_id}")
            return [
                streamer.build_oru_r01(
                    profile,
                    streamer.vitals_for_bed(profile, tick, tick * 2.0, rng)[1],
                    tick,
                    moment=_FIXED_MOMENT,
                )
                for tick in range(15)
            ]

        assert run() == run()

    def test_different_seeds_yield_different_drift(self) -> None:
        """
        Guard against the seed being ignored entirely. BED-01 is the drifting
        bed; BED-03 is deterministic by design and would not differ.
        """
        profile = next(p for p in streamer.BED_PROFILES if p.bed_id == "ICU-BED-01")

        def run(seed: int) -> list[float]:
            rng = random.Random(f"{seed}:{profile.bed_id}")
            return [
                streamer.vitals_for_bed(profile, tick, tick * 2.0, rng)[1].heart_rate
                for tick in range(15)
            ]

        assert run(1) != run(2)

    def test_bed_03_is_seed_independent_by_design(self) -> None:
        """
        The sepsis ramp is a scripted clinical narrative: jitter could push a
        parameter across a NEWS2 band boundary and break monotonicity.
        """
        profile = next(p for p in streamer.BED_PROFILES if p.bed_id == "ICU-BED-03")

        def run(seed: int) -> list[float]:
            rng = random.Random(f"{seed}:{profile.bed_id}")
            return [
                streamer.vitals_for_bed(profile, tick, tick * 2.0, rng)[1].heart_rate
                for tick in range(15)
            ]

        assert run(1) == run(2)


class TestHl7StructuralConformance:
    """HL7 v2.5.1 ORU^R01 structure, per the Phase 5 message-format spec."""

    @pytest.fixture
    def message(self) -> str:
        profile = streamer.BED_PROFILES[0]
        rng = random.Random("structure")
        _, vitals = streamer.vitals_for_bed(profile, 0, 0.0, rng)
        return streamer.build_oru_r01(profile, vitals, 0, moment=_FIXED_MOMENT)

    def test_segments_are_carriage_return_terminated_not_newline(
        self, message: str
    ) -> None:
        assert "\n" not in message, "HL7 segments must be CR-terminated, not LF."
        assert message.endswith("\r")

    def test_msh_declares_encoding_characters_and_version(self, message: str) -> None:
        msh = message.split("\r")[0].split("|")
        assert msh[0] == "MSH"
        assert msh[1] == "^~\\&"
        assert msh[8] == "ORU^R01"
        assert msh[11] == "2.5.1"

    def test_msh7_is_fourteen_digit_datetime(self, message: str) -> None:
        msh7 = message.split("\r")[0].split("|")[6]
        assert len(msh7) == 14 and msh7.isdigit(), f"MSH-7 was {msh7!r}"
        datetime.strptime(msh7, "%Y%m%d%H%M%S")  # noqa: DTZ007 - format check only

    def test_required_segments_appear_in_order(self, message: str) -> None:
        kinds = [seg.split("|")[0] for seg in message.split("\r") if seg]
        assert kinds[0] == "MSH"
        assert kinds[1] == "PID"
        assert kinds[2] == "OBR"
        assert set(kinds[3:]) == {"OBX"}

    def test_every_obx_is_final_and_timestamped(self, message: str) -> None:
        for segment in message.split("\r"):
            if not segment.startswith("OBX"):
                continue
            fields = segment.split("|")
            assert fields[11] == "F", f"OBX-11 must be F (Final): {segment}"
            assert fields[14], f"OBX-14 observation timestamp missing: {segment}"

    def test_obx_set_ids_are_sequential_from_one(self, message: str) -> None:
        ids = [
            int(seg.split("|")[1])
            for seg in message.split("\r")
            if seg.startswith("OBX")
        ]
        assert ids == list(range(1, len(ids) + 1))

    def test_avpu_is_sent_as_st_not_nm(self, message: str) -> None:
        """
        The adapter maps AVPU through _AVPU_STRINGS from an ST observation.
        Sending it as NM would skip the segment and lose the consciousness
        parameter entirely.
        """
        avpu_segments = [
            seg
            for seg in message.split("\r")
            if seg.startswith("OBX") and "76270-8" in seg
        ]
        assert len(avpu_segments) == 1
        assert avpu_segments[0].split("|")[2] == "ST"

    def test_patient_id_appears_in_pid_3(self, message: str) -> None:
        pid = message.split("\r")[1].split("|")
        assert pid[3].startswith(streamer.BED_PROFILES[0].patient_id)


class TestBannerAndProfileIntegrity:
    """The synthetic-data banner is a regulatory requirement, not decoration."""

    def test_banner_states_the_data_is_synthetic(self) -> None:
        assert "SYNTHETIC" in streamer.BANNER.upper()
        assert "NOT REAL PATIENT DATA" in streamer.BANNER.upper()

    def test_three_beds_are_defined_with_unique_identities(self) -> None:
        assert len(streamer.BED_PROFILES) == 3
        assert len({p.bed_id for p in streamer.BED_PROFILES}) == 3
        assert len({p.patient_id for p in streamer.BED_PROFILES}) == 3

    def test_patient_ids_are_visibly_synthetic(self) -> None:
        for profile in streamer.BED_PROFILES:
            assert profile.patient_id.startswith("PT-DEMO-"), (
                "Demo patient IDs must be unmistakably synthetic so a "
                "screenshot can never be mistaken for real PHI."
            )

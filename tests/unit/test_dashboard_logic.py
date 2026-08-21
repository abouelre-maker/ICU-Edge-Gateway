"""
Unit tests — demo/dashboard_logic.py (Phase 6 clinical demonstration dashboard).

FIXTURES ARE REAL. tests/fixtures/live_deltas.json was captured from an
actually-running gateway over the real WebSocket (WS /api/v1/live/vitals) by
sending real MLLP messages, not hand-authored. It covers the five shapes the
dashboard must survive:

  normal                    — news2 present, no warnings
  warnings_with_valid_score — DIASTOLIC_BP 500 rejected (audit-only, so NEWS2
                              still computes): a valid score WITH warnings and
                              a dataAbsentReason Observation
  artifact_rejected         — HEART_RATE 450 rejected. HR is NEWS2-mandatory,
                              so the score is withheld entirely: news2 is null
                              AND warnings are present
  news2_null                — HR only, insufficient data: news2 null
  unmapped_patient          — a patient_id absent from BED_MAP

The artifact_rejected case is the important one: rejecting a MANDATORY vital
means no score at all, which the dashboard must render as an explicit "no
score" state and never as a reassuring zero.

demo/dashboard_logic.py imports neither Streamlit nor Plotly, so this module
runs inside the pinned production venv (venv311) with the rest of the suite.
demo/dashboard.py is never imported here.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOGIC_PATH = _REPO_ROOT / "demo" / "dashboard_logic.py"
_FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "live_deltas.json"


def _load_logic() -> ModuleType:
    """
    Import demo/dashboard_logic.py by path.

    demo/ sits outside src/ deliberately (regulatory scope — see that
    module's docstring), so it is not on the package path.
    """
    spec = importlib.util.spec_from_file_location("dashboard_logic", _LOGIC_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


logic = _load_logic()
FIXTURES: dict[str, dict] = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def normal() -> dict:
    return FIXTURES["normal"]


@pytest.fixture
def with_warnings() -> dict:
    return FIXTURES["warnings_with_valid_score"]


@pytest.fixture
def artifact_rejected() -> dict:
    return FIXTURES["artifact_rejected"]


@pytest.fixture
def news2_null() -> dict:
    return FIXTURES["news2_null"]


@pytest.fixture
def unmapped() -> dict:
    return FIXTURES["unmapped_patient"]


class TestModuleImportsWithoutStreamlit:
    """
    The whole point of splitting dashboard_logic.py out of dashboard.py:
    logic must be testable in the production venv, where Streamlit is
    deliberately absent (it requires websockets<17 and would break the
    production pin).
    """

    def test_streamlit_and_plotly_are_not_imported(self) -> None:
        source = _LOGIC_PATH.read_text(encoding="utf-8")
        for banned in ("import streamlit", "import plotly", "import pandas"):
            assert banned not in source, (
                f"dashboard_logic.py contains {banned!r}. It must stay "
                "importable without the demo dependencies installed."
            )

    def test_logic_module_is_outside_src(self) -> None:
        """
        Regulatory scope: anything under src/ ships in the SaMD image via the
        Dockerfile's `COPY src/ ./src/`.
        """
        assert "src" not in _LOGIC_PATH.relative_to(_REPO_ROOT).parts


class TestRiskStyleMapping:
    """Colour/escalation mapping. Never decides a risk level, only renders one."""

    @pytest.mark.parametrize("level", ["NORMAL", "LOW", "LOW_MEDIUM", "MEDIUM", "HIGH"])
    def test_every_news2_risk_level_has_a_style(self, level: str) -> None:
        style = logic.risk_style(level)
        assert style.level == level
        assert style.escalation, f"{level} has no RCP escalation text"

    def test_low_medium_is_visually_distinct_from_low(self) -> None:
        """
        LOW_MEDIUM is the single-parameter-scored-3 rule: it escalates to
        1-hourly observations even though the total looks reassuring.
        Collapsing it into LOW would hide the patient the rule exists to catch.
        """
        low = logic.risk_style("LOW")
        low_medium = logic.risk_style("LOW_MEDIUM")

        assert low.background != low_medium.background
        assert low.greyscale_weight != low_medium.greyscale_weight
        assert low.marker != low_medium.marker
        assert "1-hourly" in low_medium.escalation

    def test_risk_is_not_encoded_by_hue_alone(self) -> None:
        """
        Colour-blind and greyscale legibility: each level must be separable
        without colour. Both the greyscale weight and the marker must be
        unique across all five levels.
        """
        levels = ["NORMAL", "LOW", "LOW_MEDIUM", "MEDIUM", "HIGH"]
        weights = [logic.risk_style(x).greyscale_weight for x in levels]
        markers = [logic.risk_style(x).marker for x in levels]

        assert len(set(weights)) == len(levels), f"greyscale collision: {weights}"
        assert len(set(markers)) == len(levels), f"marker collision: {markers}"

    def test_greyscale_weights_increase_with_severity(self) -> None:
        levels = ["NORMAL", "LOW", "LOW_MEDIUM", "MEDIUM", "HIGH"]
        weights = [logic.risk_style(x).greyscale_weight for x in levels]
        assert weights == sorted(weights)

    @pytest.mark.parametrize("bad", [None, "", "NONSENSE", "normal_ish"])
    def test_unknown_level_never_renders_as_green(self, bad) -> None:
        """A missing score must never be mistaken for a reassuring one."""
        style = logic.risk_style(bad)
        assert style.level == "UNKNOWN"
        assert style.background != logic.risk_style("NORMAL").background
        assert style.greyscale_weight == 0

    def test_level_lookup_is_case_insensitive(self) -> None:
        assert logic.risk_style("high").level == "HIGH"


class TestBedMapping:
    def test_the_three_demo_patients_map_to_the_three_beds(self) -> None:
        for patient_id, expected in (
            ("PT-DEMO-001", "ICU-BED-01"),
            ("PT-DEMO-002", "ICU-BED-02"),
            ("PT-DEMO-003", "ICU-BED-03"),
        ):
            bed = logic.bed_for_patient(patient_id)
            assert bed is not None and bed.bed_id == expected

    def test_only_bed_02_is_flagged_for_the_copd_scale_demo(self) -> None:
        flagged = [b.bed_id for b in logic.BED_MAP.values() if b.copd_scale_demo]
        assert flagged == ["ICU-BED-02"]

    def test_unmapped_patient_returns_none_rather_than_raising(
        self, unmapped: dict
    ) -> None:
        assert logic.bed_for_patient(unmapped["patient_id"]) is None

    def test_unmapped_patient_still_produces_a_renderable_state(
        self, unmapped: dict
    ) -> None:
        """
        An unexpected patient is information, not noise. It must survive
        parsing so the caller can render it under "Unassigned".
        """
        state = logic.bed_state_from_delta(unmapped, 100.0)
        assert state.bed is None
        assert state.patient_id == "PT-UNEXPECTED-999"
        assert state.news2_total is not None

    @pytest.mark.parametrize("value", [None, ""])
    def test_missing_patient_id_is_handled(self, value) -> None:
        assert logic.bed_for_patient(value) is None

    def test_whatif_patient_is_recognised_for_filtering(self) -> None:
        assert logic.is_whatif_patient(logic.WHATIF_PATIENT_ID) is True
        assert logic.is_whatif_patient("PT-DEMO-002") is False
        assert logic.is_whatif_patient(None) is False


class TestComponentExtraction:
    def test_all_seven_components_are_read_from_a_normal_bundle(
        self, normal: dict
    ) -> None:
        components = logic.extract_components(normal["bundle"])
        assert len(components) == 7
        assert set(components) == {cid for cid, _ in logic.COMPONENT_ORDER}

    def test_component_values_match_the_bundle_verbatim(self, normal: dict) -> None:
        """
        The dashboard reads sub-scores; it never recomputes them. Compare
        against the raw Bundle to prove no transformation happened.
        """
        components = logic.extract_components(normal["bundle"])
        observation = logic.find_news2_observation(normal["bundle"])
        assert observation is not None

        raw_total = sum(c["valueInteger"] for c in observation["component"])
        assert sum(components.values()) == raw_total

    def test_component_sum_equals_the_reported_news2_total(self, normal: dict) -> None:
        components = logic.extract_components(normal["bundle"])
        assert sum(components.values()) == normal["news2"]["total"]

    def test_missing_news2_observation_yields_empty_not_zeroes(
        self, news2_null: dict
    ) -> None:
        """
        {} means "no score"; seven zeroes would read as "all parameters
        normal" — the opposite of the truth.
        """
        assert logic.extract_components(news2_null["bundle"]) == {}

    @pytest.mark.parametrize("bundle", [None, {}, {"entry": []}, {"entry": None}])
    def test_malformed_bundles_do_not_raise(self, bundle) -> None:
        assert logic.extract_components(bundle) == {}
        assert logic.extract_warnings(bundle) == []
        assert logic.extract_vitals(bundle) == {}
        assert logic.find_news2_observation(bundle) is None


class TestWarningExtraction:
    def test_warnings_are_read_when_present(self, with_warnings: dict) -> None:
        warnings = logic.extract_warnings(with_warnings["bundle"])
        assert warnings, "fixture was captured with a rejected DIASTOLIC_BP"
        assert any("DIASTOLIC_BP" in w for w in warnings)

    def test_absent_note_means_no_warnings_not_an_error(self, normal: dict) -> None:
        assert "note" not in normal["bundle"]
        assert logic.extract_warnings(normal["bundle"]) == []

    def test_rejecting_a_mandatory_vital_withholds_the_score_entirely(
        self, artifact_rejected: dict
    ) -> None:
        """
        HEART_RATE 450 is rejected and HR is NEWS2-mandatory, so the gateway
        withholds the score. The dashboard must show warnings AND no score --
        never a zero.
        """
        assert artifact_rejected["news2"] is None
        state = logic.bed_state_from_delta(artifact_rejected, 10.0)
        assert state.news2_total is None
        assert state.warnings
        assert state.components == {}
        assert logic.risk_style(state.risk_level).level == "UNKNOWN"


class TestVitalExtraction:
    def test_numeric_vitals_are_read_with_units(self, normal: dict) -> None:
        vitals = logic.extract_vitals(normal["bundle"])
        heart_rate = vitals["heart_rate"]
        assert heart_rate.value == 72.0
        assert heart_rate.rejected is False
        assert "72" in heart_rate.display_text

    def test_the_news2_observation_is_not_mistaken_for_a_vital(
        self, normal: dict
    ) -> None:
        """
        The NEWS2 Observation shares LOINC codes with vitals in its
        component[]; the top-level resource must be skipped by SNOMED code.
        """
        vitals = logic.extract_vitals(normal["bundle"])
        for reading in vitals.values():
            assert reading.value != normal["news2"]["total"] or reading.label != "NEWS2"
        assert "news2" not in vitals

    def test_out_of_bounds_observation_renders_as_rejected_not_blank(
        self, with_warnings: dict
    ) -> None:
        """
        A blank looks like a missing sensor. REJECTED says the gateway caught
        a bad reading and stopped a false alarm — the alarm-fatigue story.
        """
        vitals = logic.extract_vitals(with_warnings["bundle"])
        rejected = [r for r in vitals.values() if r.rejected]

        assert rejected, "fixture contains a dataAbsentReason Observation"
        for reading in rejected:
            assert reading.display_text == "REJECTED"
            assert reading.display_text != ""

    def test_rejected_observation_carries_out_of_range_reason(
        self, with_warnings: dict
    ) -> None:
        found = False
        for entry in with_warnings["bundle"]["entry"]:
            reason = entry.get("resource", {}).get("dataAbsentReason")
            if reason:
                codes = [c.get("code") for c in reason.get("coding", [])]
                assert "out-of-range" in codes
                found = True
        assert found

    def test_valid_vitals_survive_alongside_a_rejected_one(
        self, with_warnings: dict
    ) -> None:
        vitals = logic.extract_vitals(with_warnings["bundle"])
        assert vitals["heart_rate"].rejected is False
        assert vitals["heart_rate"].value == 72.0


class TestBedStateFromDelta:
    def test_normal_delta_populates_every_field(self, normal: dict) -> None:
        state = logic.bed_state_from_delta(normal, 500.0)
        assert state.patient_id == "PT-DEMO-001"
        assert state.bed is not None
        assert state.news2_total == 0
        assert state.risk_level == "NORMAL"
        assert len(state.components) == 7
        assert state.source == "mllp"
        assert state.updated_monotonic == 500.0

    def test_null_news2_does_not_raise_and_leaves_total_none(
        self, news2_null: dict
    ) -> None:
        state = logic.bed_state_from_delta(news2_null, 1.0)
        assert state.news2_total is None
        assert state.risk_level is None

    def test_completely_empty_delta_is_survivable(self) -> None:
        state = logic.bed_state_from_delta({}, 0.0)
        assert state.patient_id == "UNKNOWN"
        assert state.bed is None
        assert state.news2_total is None


class TestTrendAccumulation:
    def test_readings_accumulate_per_patient_per_vital(self, normal: dict) -> None:
        store = logic.new_trend_store()
        base = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
        for index in range(5):
            state = logic.bed_state_from_delta(normal, float(index))
            logic.append_trend(store, state, base + timedelta(seconds=index))

        series = store["PT-DEMO-001"]
        for vital in logic.TREND_VITALS:
            assert len(series[vital]) == 5
        assert len(series["news2_total"]) == 5

    def test_history_is_bounded(self, normal: dict) -> None:
        store = logic.new_trend_store()
        state = logic.bed_state_from_delta(normal, 0.0)
        for _ in range(logic.TREND_MAXLEN + 120):
            logic.append_trend(store, state)

        for series in store["PT-DEMO-001"].values():
            assert isinstance(series, deque)
            assert len(series) <= logic.TREND_MAXLEN

    def test_rejected_readings_are_excluded_from_trends(
        self, with_warnings: dict
    ) -> None:
        """
        A rejected artifact must not enter the trend line, or the chart would
        plot a value the pipeline explicitly refused to score.
        """
        store = logic.new_trend_store()
        state = logic.bed_state_from_delta(with_warnings, 0.0)
        logic.append_trend(store, state)

        rejected_ids = {r.component_id for r in state.vitals.values() if r.rejected}
        for component_id in rejected_ids:
            assert component_id not in store[state.patient_id]

    def test_absent_news2_does_not_append_a_point(self, news2_null: dict) -> None:
        store = logic.new_trend_store()
        state = logic.bed_state_from_delta(news2_null, 0.0)
        logic.append_trend(store, state)
        assert "news2_total" not in store.get(state.patient_id, {})

    def test_patients_do_not_share_history(self, normal: dict, unmapped: dict) -> None:
        store = logic.new_trend_store()
        logic.append_trend(store, logic.bed_state_from_delta(normal, 0.0))
        logic.append_trend(store, logic.bed_state_from_delta(unmapped, 0.0))
        assert set(store) == {"PT-DEMO-001", "PT-UNEXPECTED-999"}


class TestConnectionState:
    """Three states, each visibly distinct. AWAITING is NOT an error."""

    def test_connected_with_no_data_is_awaiting_not_an_error(self) -> None:
        status = logic.connection_status(
            socket_connected=True, last_delta_monotonic=None, now_monotonic=10.0
        )
        assert status.state == "AWAITING_FIRST_MESSAGE"
        assert status.is_error is False

    def test_awaiting_copy_explains_the_push_only_design(self) -> None:
        """
        The presenter must not read a correctly-working push-only stream as
        a fault. The copy has to say why the screen is briefly empty.
        """
        status = logic.connection_status(
            socket_connected=True, last_delta_monotonic=None, now_monotonic=0.0
        )
        detail = status.detail.lower()
        assert "push-only" in detail
        assert "snapshot" in detail
        assert "design" in detail

    def test_recent_delta_is_live_with_age(self) -> None:
        status = logic.connection_status(
            socket_connected=True, last_delta_monotonic=98.0, now_monotonic=100.0
        )
        assert status.state == "LIVE"
        assert status.is_error is False
        assert "2.0s" in status.detail

    def test_stale_delta_is_disconnected_even_if_socket_looks_open(self) -> None:
        """A silent socket is not a live feed."""
        status = logic.connection_status(
            socket_connected=True, last_delta_monotonic=0.0, now_monotonic=999.0
        )
        assert status.state == "DISCONNECTED"
        assert status.is_error is True

    def test_closed_socket_is_disconnected(self) -> None:
        status = logic.connection_status(
            socket_connected=False, last_delta_monotonic=99.0, now_monotonic=100.0
        )
        assert status.state == "DISCONNECTED"

    def test_disconnected_reports_data_age_so_stale_is_never_shown_as_live(
        self,
    ) -> None:
        status = logic.connection_status(
            socket_connected=False, last_delta_monotonic=40.0, now_monotonic=100.0
        )
        assert "60" in status.detail
        assert "dimmed" in status.detail.lower()

    def test_disconnected_shows_reconnect_countdown(self) -> None:
        status = logic.connection_status(
            socket_connected=False,
            last_delta_monotonic=90.0,
            now_monotonic=100.0,
            reconnect_in_seconds=4.0,
        )
        assert "retrying in 4s" in status.detail

    def test_the_three_states_are_visually_distinct(self) -> None:
        awaiting = logic.connection_status(
            socket_connected=True, last_delta_monotonic=None, now_monotonic=0.0
        )
        live = logic.connection_status(
            socket_connected=True, last_delta_monotonic=0.0, now_monotonic=1.0
        )
        down = logic.connection_status(
            socket_connected=False, last_delta_monotonic=0.0, now_monotonic=1.0
        )
        colours = {awaiting.colour, live.colour, down.colour}
        labels = {awaiting.label, live.label, down.label}
        assert len(colours) == 3
        assert len(labels) == 3


class TestBackoffAndThroughput:
    def test_backoff_grows_and_is_capped(self) -> None:
        delays = [logic.backoff_delay(a) for a in range(1, 10)]
        assert delays == sorted(delays)
        assert max(delays) <= 30.0
        assert delays[0] == 1.0

    def test_messages_per_minute_is_zero_with_no_frames(self) -> None:
        assert logic.messages_per_minute([], 100.0) == 0.0

    def test_messages_per_minute_ignores_frames_outside_the_window(self) -> None:
        old = [1.0, 2.0, 3.0]
        assert logic.messages_per_minute(old, 1000.0) == 0.0

    def test_messages_per_minute_counts_recent_frames(self) -> None:
        times = [float(t) for t in range(100, 130)]
        assert logic.messages_per_minute(times, 130.0) > 0.0


class TestWhatIfPayload:
    def test_payload_carries_the_requested_scale(self, normal: dict) -> None:
        state = logic.bed_state_from_delta(normal, 0.0)
        payload = logic.build_whatif_payload(state, "SCALE_2")
        assert payload["spo2_scale"] == "SCALE_2"

    def test_payload_uses_a_distinct_patient_id(self, normal: dict) -> None:
        """What-if traffic must be filterable out of the live bed wall."""
        state = logic.bed_state_from_delta(normal, 0.0)
        payload = logic.build_whatif_payload(state, "SCALE_1")
        assert payload["patient_id"] == logic.WHATIF_PATIENT_ID
        assert payload["patient_id"] != state.patient_id
        assert logic.is_whatif_patient(payload["patient_id"])

    def test_rejected_readings_are_never_sent_for_scoring(
        self, with_warnings: dict
    ) -> None:
        """
        Smuggling a rejected artifact into a what-if would score data the
        pipeline already refused.
        """
        state = logic.bed_state_from_delta(with_warnings, 0.0)
        payload = logic.build_whatif_payload(state, "SCALE_1")

        rejected_values = {
            r.value for r in state.vitals.values() if r.rejected and r.value is not None
        }
        sent_values = {s["value"] for s in payload["samples"]}
        assert not (rejected_values & sent_values)

    def test_payload_samples_carry_the_fields_the_endpoint_requires(
        self, normal: dict
    ) -> None:
        state = logic.bed_state_from_delta(normal, 0.0)
        payload = logic.build_whatif_payload(state, "SCALE_2")
        assert payload["samples"], "no samples built from a complete bundle"
        for sample in payload["samples"]:
            assert {"vital_sign_type", "value", "unit", "timestamp"} <= set(sample)

    def test_empty_state_produces_an_empty_sample_list_not_a_crash(self) -> None:
        state = logic.bed_state_from_delta({}, 0.0)
        payload = logic.build_whatif_payload(state, "SCALE_1")
        assert payload["samples"] == []


class TestNews2HeaderReading:
    def test_lowercase_headers_are_read(self) -> None:
        """uvicorn lower-cases response header names."""
        total, risk = logic.read_news2_headers(
            {"x-news2-total": "7", "x-news2-risk-level": "HIGH"}
        )
        assert total == 7
        assert risk == "HIGH"

    def test_documented_titlecase_spelling_is_also_read(self) -> None:
        total, risk = logic.read_news2_headers(
            {"X-NEWS2-Total": "3", "X-NEWS2-Risk-Level": "LOW"}
        )
        assert total == 3
        assert risk == "LOW"

    @pytest.mark.parametrize(
        "headers", [{}, None, {"content-type": "application/json"}]
    )
    def test_absent_headers_yield_none_not_zero(self, headers) -> None:
        """
        Zero would be a valid NEWS2 total. A missing header must never be
        rendered as a real score of 0.
        """
        total, risk = logic.read_news2_headers(headers)
        assert total is None
        assert risk is None

    def test_unparseable_total_yields_none(self) -> None:
        total, _ = logic.read_news2_headers({"x-news2-total": "not-a-number"})
        assert total is None


class TestScaleComparison:
    def test_difference_and_band_crossing_are_reported(self) -> None:
        comparison = logic.ScaleComparison(
            scale_1_total=5,
            scale_1_risk="MEDIUM",
            scale_2_total=2,
            scale_2_risk="LOW",
        )
        assert comparison.difference == 3
        assert comparison.crosses_risk_band is True

    def test_same_band_is_not_reported_as_crossing(self) -> None:
        comparison = logic.ScaleComparison(
            scale_1_total=2, scale_1_risk="LOW", scale_2_total=1, scale_2_risk="LOW"
        )
        assert comparison.crosses_risk_band is False

    def test_missing_result_yields_no_difference_rather_than_a_wrong_one(self) -> None:
        comparison = logic.ScaleComparison(
            scale_1_total=None, scale_1_risk=None, scale_2_total=2, scale_2_risk="LOW"
        )
        assert comparison.difference is None
        assert comparison.crosses_risk_band is False

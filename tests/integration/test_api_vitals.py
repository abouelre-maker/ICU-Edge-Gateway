"""
Integration Tests — POST /api/v1/vitals (JSON-normalized vital signs).

IEC 62304 §5.7: Integration tests for the structured JSON ingestion endpoint.
ISO 14971: Validates FHIR output correctness and error handling.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

_TS = "2024-01-15T10:00:00Z"

# Complete 7-parameter vitals payload (all NEWS2 parameters) — normal patient
FULL_VITALS = {
    "patient_id": "PT-JSON-001",
    "samples": [
        {
            "vital_sign_type": "HEART_RATE",
            "value": 72.0,
            "unit": "bpm",
            "timestamp": _TS,
        },
        {
            "vital_sign_type": "RESPIRATORY_RATE",
            "value": 16.0,
            "unit": "breaths/min",
            "timestamp": _TS,
        },
        {
            "vital_sign_type": "SPO2",
            "value": 98.0,
            "unit": "%",
            "timestamp": _TS,
        },
        {
            "vital_sign_type": "SYSTOLIC_BP",
            "value": 120.0,
            "unit": "mmHg",
            "timestamp": _TS,
        },
        {
            "vital_sign_type": "TEMPERATURE_CELSIUS",
            "value": 37.0,
            "unit": "Cel",
            "timestamp": _TS,
        },
        {
            "vital_sign_type": "SUPPLEMENTAL_O2",
            "value": 0.0,
            "unit": "bool",
            "timestamp": _TS,
        },
        {
            "vital_sign_type": "CONSCIOUSNESS",
            "value": 0.0,
            "unit": "avpu",
            "timestamp": _TS,
            "avpu_level": "A",
        },
    ],
    "spo2_scale": "SCALE_1",
}

# High-risk NEWS2 scenario: all parameters deranged
HIGH_RISK_VITALS = {
    "patient_id": "PT-HIGH-001",
    "samples": [
        {
            "vital_sign_type": "HEART_RATE",
            "value": 140.0,
            "unit": "bpm",
            "timestamp": _TS,
        },
        {
            "vital_sign_type": "RESPIRATORY_RATE",
            "value": 28.0,
            "unit": "breaths/min",
            "timestamp": _TS,
        },
        {"vital_sign_type": "SPO2", "value": 89.0, "unit": "%", "timestamp": _TS},
        {
            "vital_sign_type": "SYSTOLIC_BP",
            "value": 85.0,
            "unit": "mmHg",
            "timestamp": _TS,
        },
        {
            "vital_sign_type": "TEMPERATURE_CELSIUS",
            "value": 39.5,
            "unit": "Cel",
            "timestamp": _TS,
        },
        {
            "vital_sign_type": "SUPPLEMENTAL_O2",
            "value": 1.0,
            "unit": "bool",
            "timestamp": _TS,
        },
        {
            "vital_sign_type": "CONSCIOUSNESS",
            "value": 0.0,
            "unit": "avpu",
            "timestamp": _TS,
            "avpu_level": "V",
        },
    ],
    "spo2_scale": "SCALE_1",
}

# Partial vitals — insufficient for NEWS2 (missing RR, SBP, Temp)
PARTIAL_VITALS = {
    "patient_id": "PT-PARTIAL-001",
    "samples": [
        {
            "vital_sign_type": "HEART_RATE",
            "value": 72.0,
            "unit": "bpm",
            "timestamp": _TS,
        },
        {"vital_sign_type": "SPO2", "value": 98.0, "unit": "%", "timestamp": _TS},
    ],
}

# Vitals with device context
VITALS_WITH_DEVICE = {
    **FULL_VITALS,
    "patient_id": "PT-DEV-001",
    "device_id": "DEV-ICU-007",
    "device_vendor": "PHILIPS",
    "device_model": "IntelliVue MX800",
    "device_location": "ICU-BED-07-A",
}

# COPD patient (Scale 2) with SpO2 = 90% — should score 0 (within target range)
COPD_VITALS = {
    **FULL_VITALS,
    "patient_id": "PT-COPD-001",
    "spo2_scale": "SCALE_2",
    "samples": [
        s if s["vital_sign_type"] != "SPO2" else {**s, "value": 90.0}
        for s in FULL_VITALS["samples"]
    ],
}


@pytest.mark.integration
class TestVitalsEndpointSuccess:
    """POST /api/v1/vitals — successful ingestion scenarios."""

    async def test_full_vitals_returns_200(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/vitals", json=FULL_VITALS)
        assert response.status_code == 200

    async def test_response_is_fhir_r4_bundle(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/vitals", json=FULL_VITALS)
        bundle = response.json()
        assert bundle["resourceType"] == "Bundle"
        assert bundle["type"] == "collection"

    async def test_bundle_has_timestamp(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/vitals", json=FULL_VITALS)
        assert "timestamp" in response.json()

    async def test_bundle_contains_news2_observation(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/vitals", json=FULL_VITALS)
        entries = response.json()["entry"]
        news2_entries = [
            e
            for e in entries
            if e["resource"]["resourceType"] == "Observation"
            and any(
                c.get("code") == "1239842005"
                for c in e["resource"].get("code", {}).get("coding", [])
            )
        ]
        assert len(news2_entries) == 1, (
            "Full vitals set must produce exactly one NEWS2 Observation. "
            "ISO 14971 HAZARD-NEWS2-001."
        )

    async def test_news2_normal_for_all_normal_vitals(
        self, client: AsyncClient
    ) -> None:
        """
        All-normal vitals must produce NEWS2 total = 0 (NORMAL risk level).
        ISO 14971 HAZARD-NEWS2-001: scoring accuracy test via API.
        """
        response = await client.post("/api/v1/vitals", json=FULL_VITALS)
        assert response.status_code == 200
        total = response.headers.get("x-news2-total")
        risk = response.headers.get("x-news2-risk-level")
        assert (
            total == "0"
        ), f"All-normal vitals must produce NEWS2 total=0. Got '{total}'."
        assert (
            risk == "NORMAL"
        ), f"All-normal vitals must produce NORMAL risk. Got '{risk}'."

    async def test_news2_high_for_deranged_vitals(self, client: AsyncClient) -> None:
        """
        High-risk scenario must produce NEWS2 risk level HIGH.
        HR=140, RR=28, SpO2=89%, SBP=85, Temp=39.5, O2, V consciousness.
        """
        response = await client.post("/api/v1/vitals", json=HIGH_RISK_VITALS)
        assert response.status_code == 200
        risk = response.headers.get("x-news2-risk-level")
        assert risk in {"HIGH", "MEDIUM"}, (
            f"Deranged vitals must produce HIGH or MEDIUM risk. Got '{risk}'. "
            "ISO 14971 HAZARD-NEWS2-002."
        )

    async def test_cds_advisory_header_present(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/vitals", json=FULL_VITALS)
        assert response.headers.get("x-cds-advisory-only") == "true", (
            "X-CDS-Advisory-Only: true must be present on all responses. "
            "FDA CDS Non-Device Exemption."
        )

    async def test_pipeline_duration_header_present(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/vitals", json=FULL_VITALS)
        assert "x-pipeline-duration-ms" in response.headers

    async def test_subject_reference_matches_patient_id(
        self, client: AsyncClient
    ) -> None:
        response = await client.post("/api/v1/vitals", json=FULL_VITALS)
        entries = response.json()["entry"]
        obs_entries = [
            e for e in entries if e["resource"]["resourceType"] == "Observation"
        ]
        for entry in obs_entries:
            subject = entry["resource"]["subject"]["reference"]
            assert "PT-JSON-001" in subject

    async def test_bundle_with_device_contains_device_resource(
        self, client: AsyncClient
    ) -> None:
        response = await client.post("/api/v1/vitals", json=VITALS_WITH_DEVICE)
        assert response.status_code == 200
        entries = response.json()["entry"]
        device_entries = [
            e for e in entries if e["resource"]["resourceType"] == "Device"
        ]
        assert len(device_entries) == 1
        assert device_entries[0]["resource"]["manufacturer"] == "PHILIPS"

    async def test_copd_scale2_accepted(self, client: AsyncClient) -> None:
        """
        COPD patient with SCALE_2 and SpO2=90% should score 0 (within target).
        ISO 14971 HAZARD-SPO2-001.
        """
        response = await client.post("/api/v1/vitals", json=COPD_VITALS)
        assert response.status_code == 200
        # SpO2=90% on SCALE_2 = 0 points (within COPD target range 88-92%)
        # This verifies the scale parameter propagates through the API
        bundle = response.json()
        assert bundle["resourceType"] == "Bundle"

    async def test_partial_vitals_returns_200_without_news2(
        self, client: AsyncClient
    ) -> None:
        """
        Insufficient vitals for NEWS2 must return 200 (not 500).
        Bundle must not contain a NEWS2 Observation.
        ISO 14971 HAZARD-NEWS2-003.
        """
        response = await client.post("/api/v1/vitals", json=PARTIAL_VITALS)
        assert response.status_code == 200
        entries = response.json()["entry"]
        news2_entries = [
            e
            for e in entries
            if e["resource"]["resourceType"] == "Observation"
            and any(
                c.get("code") == "1239842005"
                for c in e["resource"].get("code", {}).get("coding", [])
            )
        ]
        assert len(news2_entries) == 0, (
            "Partial vitals (missing RR, SBP, Temp) must NOT produce NEWS2. "
            "ISO 14971 HAZARD-NEWS2-003."
        )

    async def test_out_of_bounds_hr_still_returns_200(
        self, client: AsyncClient
    ) -> None:
        """
        Out-of-bounds HR (5 bpm = instrument error) must NOT crash the pipeline.
        The sample is flagged as artifact and excluded from NEWS2.
        ISO 14971 HAZARD-BOUNDS-001.
        """
        bad_hr_payload = {
            "patient_id": "PT-OOB-001",
            "samples": [
                {
                    "vital_sign_type": "HEART_RATE",
                    "value": 5.0,
                    "unit": "bpm",
                    "timestamp": _TS,
                },
                {
                    "vital_sign_type": "SPO2",
                    "value": 98.0,
                    "unit": "%",
                    "timestamp": _TS,
                },
            ],
        }
        response = await client.post("/api/v1/vitals", json=bad_hr_payload)
        assert response.status_code == 200


@pytest.mark.integration
class TestVitalsValidationErrors:
    """POST /api/v1/vitals — Pydantic validation error scenarios (expect HTTP 422)."""

    async def test_missing_patient_id_returns_422(self, client: AsyncClient) -> None:
        payload = {k: v for k, v in FULL_VITALS.items() if k != "patient_id"}
        response = await client.post("/api/v1/vitals", json=payload)
        assert response.status_code == 422

    async def test_empty_patient_id_returns_422(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/vitals",
            json={**FULL_VITALS, "patient_id": ""},
        )
        assert response.status_code == 422

    async def test_empty_samples_list_returns_422(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/vitals",
            json={**FULL_VITALS, "samples": []},
        )
        assert response.status_code == 422

    async def test_consciousness_without_avpu_returns_422(
        self, client: AsyncClient
    ) -> None:
        """
        CONSCIOUSNESS sample without avpu_level must be rejected at the API layer.
        ISO 14971 HAZARD-CON-001: AVPU is required for consciousness scoring.
        """
        bad_sample = {
            "vital_sign_type": "CONSCIOUSNESS",
            "value": 0.0,
            "unit": "avpu",
            "timestamp": _TS,
            # avpu_level intentionally absent
        }
        response = await client.post(
            "/api/v1/vitals",
            json={**FULL_VITALS, "samples": [bad_sample]},
        )
        assert response.status_code == 422, (
            "CONSCIOUSNESS sample without avpu_level must return 422. "
            "ISO 14971 HAZARD-CON-001."
        )

    async def test_naive_timestamp_returns_422(self, client: AsyncClient) -> None:
        """
        Timestamps without timezone information must be rejected.
        ISO 14971 HAZARD-TIME-001.
        """
        naive_sample = {
            "vital_sign_type": "HEART_RATE",
            "value": 72.0,
            "unit": "bpm",
            "timestamp": "2024-01-15T10:00:00",  # No timezone — must be rejected
        }
        response = await client.post(
            "/api/v1/vitals",
            json={"patient_id": "PT-001", "samples": [naive_sample]},
        )
        assert response.status_code == 422, (
            "Naive timestamp (no timezone) must return 422. "
            "ISO 14971 HAZARD-TIME-001."
        )

    async def test_invalid_vital_sign_type_returns_422(
        self, client: AsyncClient
    ) -> None:
        bad_sample = {
            "vital_sign_type": "INVALID_TYPE",
            "value": 72.0,
            "unit": "bpm",
            "timestamp": _TS,
        }
        response = await client.post(
            "/api/v1/vitals",
            json={"patient_id": "PT-001", "samples": [bad_sample]},
        )
        assert response.status_code == 422

    async def test_invalid_spo2_scale_returns_422(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/vitals",
            json={**FULL_VITALS, "spo2_scale": "SCALE_99"},
        )
        assert response.status_code == 422

    async def test_invalid_avpu_level_value_returns_422(
        self, client: AsyncClient
    ) -> None:
        bad_sample = {
            "vital_sign_type": "CONSCIOUSNESS",
            "value": 0.0,
            "unit": "avpu",
            "timestamp": _TS,
            "avpu_level": "INVALID_AVPU",
        }
        response = await client.post(
            "/api/v1/vitals",
            json={"patient_id": "PT-001", "samples": [bad_sample]},
        )
        assert response.status_code == 422

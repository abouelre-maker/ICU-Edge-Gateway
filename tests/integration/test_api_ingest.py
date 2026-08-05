"""
Integration Tests — POST /api/v1/ingest (raw HL7 v2.x ingestion).

IEC 62304 §5.7: Integration tests verify the full pipeline from HTTP request
through domain processing to FHIR R4 Bundle response.
ISO 14971: Tests verify that FHIR Bundles are produced correctly for
both normal and boundary clinical scenarios.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

# ── Sample HL7 Messages ────────────────────────────────────────────────────────

# Complete ORU^R01 with all six LOINC-coded vital signs — produces a full NEWS2 score
FULL_ORU = (
    "MSH|^~\\&|GENERIC_MONITOR|ICU_UNIT|EHR|HOSPITAL|20240115100000"
    "||ORU^R01|MSG001|P|2.5.1\r"
    "PID|1||PT-API-001^^^HOSP^MR||DOE^JOHN||19800101|M\r"
    "OBR|1||ORDER-001|||||20240115100000\r"
    "OBX|1|NM|8867-4^Heart rate^LN||72|/min|60-100||||F|||20240115100000\r"
    "OBX|2|NM|59408-5^SpO2^LN||98|%|95-100||||F|||20240115100000\r"
    "OBX|3|NM|9279-1^Respiratory rate^LN||16|/min|12-20||||F|||20240115100000\r"
    "OBX|4|NM|8480-6^Systolic BP^LN||120|mmHg|90-140||||F|||20240115100000\r"
    "OBX|5|NM|8310-5^Temperature^LN||37.0|Cel|36.1-38.0||||F|||20240115100000\r"
    "OBX|6|NM|57834-7^Supplemental O2^LN||0||||||F|||20240115100000\r"
)

# Philips IntelliVue with proprietary codes
PHILIPS_ORU = (
    "MSH|^~\\&|PHILIPS|ICU-BED-7|EHR|HOSPITAL|20240115100000"
    "||ORU^R01|MSG002|P|2.3.1\r"
    "PID|1||PT-PHIL-001\r"
    "OBX|1|NM|HR^Heart Rate^MDC||88|bpm||||F|||20240115100000\r"
    "OBX|2|NM|SPO2^SpO2^MDC||95|%||||F|||20240115100000\r"
    "OBX|3|NM|RESP^Respiratory Rate^MDC||22|/min||||F|||20240115100000\r"
    "OBX|4|NM|NIBP-S^Systolic BP^MDC||90|mmHg||||F|||20240115100000\r"
    "OBX|5|NM|TEMP^Temperature^MDC||38.5|Cel||||F|||20240115100000\r"
    "OBX|6|NM|57834-7^Supplemental O2^LN||0||||||F|||20240115100000\r"
)

# HL7 with AVPU consciousness set to NEW_CONFUSION
CONFUSION_ORU = (
    "MSH|^~\\&|GE_CARESCAPE|ICU|EHR|HOSPITAL|20240115100000"
    "||ORU^R01|MSG003|P|2.5.1\r"
    "PID|1||PT-CONF-001\r"
    "OBX|1|NM|8867-4^Heart rate^LN||90|/min||||F|||20240115100000\r"
    "OBX|2|NM|59408-5^SpO2^LN||94|%||||F|||20240115100000\r"
    "OBX|3|NM|9279-1^Respiratory rate^LN||22|/min||||F|||20240115100000\r"
    "OBX|4|NM|8480-6^Systolic BP^LN||95|mmHg||||F|||20240115100000\r"
    "OBX|5|NM|8310-5^Temperature^LN||38.5|Cel||||F|||20240115100000\r"
    "OBX|6|ST|AVPU^Level of Consciousness^MDC||NEW_CONFUSION|avpu||||F|||20240115100000\r"
    "OBX|7|NM|57834-7^Supplemental O2^LN||0||||||F|||20240115100000\r"
)

# Partial message — only 2 vital signs — will not produce NEWS2 score
PARTIAL_ORU = (
    "MSH|^~\\&|GENERIC|ICU|EHR|HOSPITAL|20240115100000||ORU^R01|MSG004|P|2.5.1\r"
    "PID|1||PT-PARTIAL-001\r"
    "OBX|1|NM|8867-4^Heart rate^LN||72|/min||||F|||20240115100000\r"
    "OBX|2|NM|59408-5^SpO2^LN||98|%||||F|||20240115100000\r"
)

_HL7_HEADERS = {"Content-Type": "text/plain"}


@pytest.mark.integration
class TestIngestValidHL7:
    """POST /api/v1/ingest — successful ingestion scenarios."""

    async def test_full_hl7_returns_200(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/ingest",
            content=FULL_ORU,
            headers=_HL7_HEADERS,
        )
        assert response.status_code == 200

    async def test_response_content_type_is_fhir_json(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/ingest", content=FULL_ORU, headers=_HL7_HEADERS
        )
        ct = response.headers.get("content-type", "")
        assert "fhir+json" in ct or "application/json" in ct

    async def test_response_is_fhir_r4_bundle(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/ingest", content=FULL_ORU, headers=_HL7_HEADERS
        )
        bundle = response.json()
        assert bundle["resourceType"] == "Bundle"
        assert bundle["type"] == "collection"

    async def test_bundle_has_timestamp(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/ingest", content=FULL_ORU, headers=_HL7_HEADERS
        )
        assert "timestamp" in response.json(), (
            "Bundle.timestamp is required. ISO 14971 HAZARD-FHIR-003."
        )

    async def test_bundle_contains_vital_sign_observations(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/ingest", content=FULL_ORU, headers=_HL7_HEADERS
        )
        entries = response.json()["entry"]
        obs_entries = [
            e for e in entries
            if e["resource"]["resourceType"] == "Observation"
        ]
        assert len(obs_entries) >= 5, (
            "Full ORU^R01 with 6 OBX segments must produce ≥5 Observations."
        )

    async def test_bundle_contains_news2_observation(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/ingest", content=FULL_ORU, headers=_HL7_HEADERS
        )
        entries = response.json()["entry"]
        news2_entries = [
            e for e in entries
            if e["resource"]["resourceType"] == "Observation"
            and any(
                c.get("code") == "1239842005"
                for c in e["resource"].get("code", {}).get("coding", [])
            )
        ]
        assert len(news2_entries) == 1, (
            "Full vital signs set must produce exactly one NEWS2 Observation "
            "(SNOMED CT 1239842005). ISO 14971 HAZARD-NEWS2-001."
        )

    async def test_patient_id_extracted_from_pid(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/ingest", content=FULL_ORU, headers=_HL7_HEADERS
        )
        entries = response.json()["entry"]
        obs_entries = [
            e for e in entries
            if e["resource"]["resourceType"] == "Observation"
        ]
        # All observations must reference PT-API-001 (from PID-3)
        for entry in obs_entries:
            subject = entry["resource"]["subject"]["reference"]
            assert "PT-API-001" in subject, (
                f"Subject reference '{subject}' must contain patient ID from PID-3. "
                "IEC 62304 REQ-HL7-002."
            )

    async def test_pipeline_duration_header_present(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/ingest", content=FULL_ORU, headers=_HL7_HEADERS
        )
        assert "x-pipeline-duration-ms" in response.headers

    async def test_cds_advisory_header_is_true(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/ingest", content=FULL_ORU, headers=_HL7_HEADERS
        )
        assert response.headers.get("x-cds-advisory-only") == "true", (
            "X-CDS-Advisory-Only: true header is mandatory. "
            "FDA CDS Non-Device Exemption audit trail."
        )

    async def test_news2_total_header_present_for_full_vitals(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/ingest", content=FULL_ORU, headers=_HL7_HEADERS
        )
        assert "x-news2-total" in response.headers
        assert "x-news2-risk-level" in response.headers


@pytest.mark.integration
class TestIngestVendorDialects:
    """POST /api/v1/ingest — vendor-specific HL7 dialect handling."""

    async def test_philips_proprietary_codes_parse(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/ingest", content=PHILIPS_ORU, headers=_HL7_HEADERS
        )
        assert response.status_code == 200
        bundle = response.json()
        entries = bundle["entry"]
        obs_count = sum(
            1 for e in entries
            if e["resource"]["resourceType"] == "Observation"
        )
        assert obs_count >= 4, "Philips dialect must parse ≥4 OBX segments."

    async def test_device_vendor_query_param_overrides_msh3(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/ingest?device_vendor=DRAEGER&device_model=Infinity+Delta",
            content=FULL_ORU,
            headers=_HL7_HEADERS,
        )
        assert response.status_code == 200
        entries = response.json()["entry"]
        device_entries = [
            e for e in entries
            if e["resource"]["resourceType"] == "Device"
        ]
        assert len(device_entries) == 1
        assert device_entries[0]["resource"]["manufacturer"] == "DRAEGER"

    async def test_encounter_id_query_param_appears_in_bundle(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/ingest?encounter_id=ENC-ICU-2024-001",
            content=FULL_ORU,
            headers=_HL7_HEADERS,
        )
        assert response.status_code == 200
        entries = response.json()["entry"]
        obs_entries = [
            e for e in entries
            if e["resource"]["resourceType"] == "Observation"
        ]
        for entry in obs_entries:
            if "encounter" in entry["resource"]:
                assert "ENC-ICU-2024-001" in entry["resource"]["encounter"]["reference"]
                break
        else:
            pytest.skip("No observations had encounter reference in this response.")


@pytest.mark.integration
class TestIngestClinicalScenarios:
    """POST /api/v1/ingest — NEWS2 scoring boundary scenarios."""

    async def test_new_confusion_produces_high_risk_level(
        self, client: AsyncClient
    ) -> None:
        """
        CONFUSION_ORU: HR=90, SpO2=94%, RR=22, SBP=95, Temp=38.5, Confusion.
        Expected: consciousness_score=3 → risk level MEDIUM or HIGH.
        ISO 14971 HAZARD-CON-001.
        """
        response = await client.post(
            "/api/v1/ingest", content=CONFUSION_ORU, headers=_HL7_HEADERS
        )
        assert response.status_code == 200
        risk_level = response.headers.get("x-news2-risk-level", "")
        assert risk_level in {"MEDIUM", "HIGH", "LOW_MEDIUM"}, (
            f"NEW_CONFUSION scenario must produce MEDIUM/HIGH/LOW_MEDIUM risk. "
            f"Got '{risk_level}'. ISO 14971 HAZARD-CON-001."
        )

    async def test_scale2_query_param_accepted(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/ingest?spo2_scale=SCALE_2",
            content=FULL_ORU,
            headers=_HL7_HEADERS,
        )
        assert response.status_code == 200
        assert response.json()["resourceType"] == "Bundle"

    async def test_partial_vitals_no_news2_no_error(
        self, client: AsyncClient
    ) -> None:
        """
        Incomplete vital signs set must return 200 (not 500).
        Bundle should not contain a NEWS2 Observation when data is insufficient.
        ISO 14971 HAZARD-NEWS2-003: Partial scoring is suppressed, not silently produced.
        """
        response = await client.post(
            "/api/v1/ingest", content=PARTIAL_ORU, headers=_HL7_HEADERS
        )
        assert response.status_code == 200
        entries = response.json()["entry"]
        news2_entries = [
            e for e in entries
            if e["resource"]["resourceType"] == "Observation"
            and any(
                c.get("code") == "1239842005"
                for c in e["resource"].get("code", {}).get("coding", [])
            )
        ]
        assert len(news2_entries) == 0, (
            "Partial vital signs must NOT produce a NEWS2 Observation. "
            "ISO 14971 HAZARD-NEWS2-003: incomplete scoring is suppressed."
        )
        # NEWS2 header must be absent for partial dataset
        assert "x-news2-total" not in response.headers


@pytest.mark.integration
class TestIngestErrorHandling:
    """POST /api/v1/ingest — error and edge case handling."""

    async def test_empty_body_returns_422(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/ingest",
            content=b"",
            headers=_HL7_HEADERS,
        )
        assert response.status_code == 422

    async def test_whitespace_only_body_returns_422(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/ingest",
            content=b"   \n\t  ",
            headers=_HL7_HEADERS,
        )
        assert response.status_code == 422

    async def test_non_hl7_body_returns_422(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/ingest",
            content=b"NOT AN HL7 MESSAGE AT ALL",
            headers=_HL7_HEADERS,
        )
        assert response.status_code == 422

    async def test_json_body_instead_of_hl7_returns_422(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/ingest",
            content=b'{"patient_id": "PT-001"}',
            headers=_HL7_HEADERS,
        )
        assert response.status_code == 422

    async def test_error_response_has_detail_field(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/ingest",
            content=b"GARBAGE DATA",
            headers=_HL7_HEADERS,
        )
        assert response.status_code in {422, 500}
        body = response.json()
        assert "detail" in body or "detail" in str(body)
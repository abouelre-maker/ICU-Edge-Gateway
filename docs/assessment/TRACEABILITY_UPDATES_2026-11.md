# Traceability updates (2026-11-19) — APPLIED

**Status:** applied to RMF-001, SRS-001, SAD-001 and RTM-001 on 2026-11-19 at the project
owner's instruction. New IDs: HAZARD-SEC-001, HAZARD-SEC-002, REQ-API-011, REQ-SEC-001,
REQ-SEC-002. New hazards are unscored and still need the clinical safety reviewer (HD-E4).
The list below is kept as the record of what was changed.

History: this list was first produced by a read-only SaMD safety review, while the
controlled documents were still unedited. Every item below has since been applied (the
"(new ID needed)" rows became HAZARD-SEC-001 and HAZARD-SEC-002). What remains open is
scoring and ratification by the clinical safety reviewer (HD-E4), not editing.

## RMF-001 Risk Management File
| Hazard | Location | Update needed |
|---|---|---|
| HAZARD-STREAM-001 | RMF-001 §HAZARD-STREAM-001 (review trigger "any change to mllp_listener.py framing logic" has fired) | Oversized frame now answered AR then closed (F03-1); add MSH-10 de-duplication and its residual risk (only byte-identical retransmissions are skipped; reused ID with new content is processed and logged). |
| HAZARD-STREAM-006 | RMF-001 §HAZARD-STREAM-006 | "Delivery is trusted (not re-checked)" is stale: delivery re-resolves the host and requires public addresses; redirects never followed; legacy IP forms refused. Residual: sub-second DNS-rebinding window. |
| HAZARD-STREAM-009 | RMF-001 §HAZARD-STREAM-009 | Add evidence: digest comparison of the registration secret, subscription cap (50), in-flight cap (100), header validation and redaction. |
| (new ID needed) | — | Unauthenticated clinical data injection on HTTP/WS (F-01/F-08) — mitigated by API keys; no existing hazard covers it. |
| (new ID needed) | — | PHI disclosure via MQTT topics and logs (F-04/F-12) — mitigated by HMAC topic segment and log pseudonymisation. |

## SRS-001
- REQ-API-001 covers only the ValueError handler. The RequestValidationError handler (422
  without the offending input) has no requirement ID — new requirement needed.
- Authentication (GATEWAY_API_KEYS, fail-closed startup) has no requirement ID — new requirement needed.

## SAD-001 stale statements
- Base image named as python:3.11-alpine3.19 — now python:3.11-alpine3.23 pinned by digest, installed from requirements.lock with hashes.
- Two exception handlers listed — now three (RequestValidationError added).
- "No structlog.configure call" — src/infrastructure/log_privacy.py now prepends a pseudonymisation processor.
- Config accessor count ("17") — new accessors: get_gateway_api_keys, validate_gateway_auth_config, get_mqtt_topic_key, get_mllp_allowed_networks.
- MLLPListener line numbers; MQTT topic format (now prefix/HMAC segment, MQTT_TOPIC_KEY required); subscription delivery path.
- Bundle structure: no note/extension/total; meta.tag version; content-derived IDs (H-01..H-04).

## RTM-001
- REQ-API-001 row: add tests/integration/test_f12_f13_privacy.py.
- HAZARD-STREAM-001..004 rows: add tests/integration/test_a8_mllp_dedup.py, tests/integration/test_f01_f08_auth_wired.py, tests/unit/test_f01_f08_auth.py.
- FHIR rows: add tests/unit/test_h01_h06_fhir_validity.py.

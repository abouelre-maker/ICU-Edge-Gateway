# RTM-001 — Requirements Traceability Matrix

## ICU Edge-to-FHIR Interoperability Gateway v1.0.0

> ## ⚠ STATUS BANNER — READ BEFORE USING THIS DOCUMENT FOR ANY PURPOSE
>
> **No credentialed Clinical Safety Officer is appointed.** The only sign-off authority that
> exists is an **interim, non-clinically-credentialed engineering appointment**
> ([docs/CSO_Role_Appointment_Brief.md](CSO_Role_Appointment_Brief.md) §5 — Housam Abouelreish,
> project owner, effective 2026-08-10) — scope limited to HAZARD-DSP-007 and HAZARD-STREAM-012
> only. It does **not** ratify any requirement, hazard, or test-adequacy claim in this document.
>
> **This matrix is a cross-check of two existing engineering-drafted documents**
> ([SRS-001](SRS-001_Software_Requirements_Specification.md),
> [RMF-001](RMF-001_Risk_Management_File.md)) **against the current source tree, not an
> independent regulatory determination.** Every cell below was checked against an actual
> file/line/test at compilation time; where that check failed or was impossible, the cell says
> so instead of being filled with an assumption.
>
> **FDA / Health Canada regulatory classification is an engineering assumption, not a regulatory
> determination** — see RMF-001's banner, which this document inherits unchanged.

---

**Document ID:** RTM-001
**Status:** DRAFT — engineering-compiled working document. Not a certified traceability matrix.
**Prepared:** 2026-08-10, Phase 5-Stream Section E, deliverable 3 (per SRS-001 §5).
**Method:** Every row's Requirement/Design/Hazard/Test cell was checked directly against source
(`grep`/`sed` against actual file content) or an existing test file's actual class/function
names — not transcribed from memory or from SRS-001/RMF-001 prose without re-verification. Row
count and coverage numbers below are counted from this file's own table, not asserted.

---

## 1. Scope and Source Documents

| Column | Populated from |
|---|---|
| Requirement | SRS-001 §3 — every `REQ-*` ID found in `src/` (17 total, confirmed by re-running the same `grep -rno "REQ-[A-Z0-9-]*" src/` this session that seeded SRS-001) |
| Design Artifact | Re-derived directly from source in this compilation — the class/function at the cited file:line |
| Hazard Link | RMF-001 §3/Appendix A — cross-checked that the cited `HAZARD-*` ID exists in RMF-001's register (40 entries as of 2026-08-10's correction pass — see §6.1) |
| Test | Re-verified this session: the cited file exists, and the cited class/function name exists in it (see §4) |

Rows are grouped in the same subsystem order as SRS-001 §3 (request-flow order).

## 2. Item 1 — Phase 5-Stream Requirement-Tracing Decision (addressed explicitly, not silently)

**Question:** should `REQ-*` tags be retroactively added to `src/infrastructure/streaming/` and
`src/infrastructure/provisioning/` now, so this matrix has rows for that layer — or should the
matrix show that layer as its own honest, explicit gap?

**Decision: explicit gap. No retroactive `REQ-*` tags were added to source for this matrix.**

**Rationale:**

1. **SRS-001's own stated method is reverse-derivation, not invention** (SRS-001 §1.1/front
   matter: "requirements were extracted from shipped code and tests, not written first and
   implemented second... this document should be read as documenting what the system *does*").
   Writing new `REQ-*` tags into `streaming`/`provisioning` source *for the purpose of* filling
   this matrix's rows would invert that method: it would make the matrix (and any future SRS
   regeneration re-seeded from source) present engineering-assistant-authored labels as if they
   were pre-existing extracted requirements. That is a traceability-integrity risk in a document
   whose entire value proposition is "checked against source, not asserted."
2. **The layer is not unowned or unreviewed** — it carries 12 `HAZARD-STREAM-*` tags (see §5
   below for the full count, including a discrepancy this compilation found) plus
   `HAZARD-ARCH-001`/`HAZARD-DSP-007` cross-references, all traceable to source line and (for
   006-012) to RMF-001's register. It is hazard-tracked. It is not requirement-tracked. These
   are genuinely different states, and collapsing them by manufacturing requirement tags would
   hide that distinction rather than resolve it.
3. Retroactively-authored requirements would need the same "is this a docstring restated as
   SHALL, or an invented statement" scrutiny SRS-001 §1.1 already applies to existing tags — that
   review has not happened for this layer and doing it under this task's time-box would repeat
   SRS-001's own caveat about restating design-intent prose as formal requirements, but this time
   for text that did not exist in source at all before this session.

**Consequence:** §3.7 below lists this layer's `HAZARD-STREAM-*`/provisioning coverage as
**"hazard-tracked, requirement-tracking not yet applied"** — an explicit, separate section, not
absent rows silently implying full coverage or silently implying no risk work exists.

**This decision is engineering-scoped, not final.** It should be revisited by whoever owns
QMS-001/SRS-001 going forward (see RMF-001 §9's identical open question about HAZARD-DSP-004)
— recorded here as a call made to produce this deliverable, not as a closed question.

## 3. Requirement → Design → Hazard → Test Matrix

### 3.1 Device / Vendor Context

| Requirement | Design Artifact | Hazard Link | Test |
|---|---|---|---|
| REQ-DEV-001 | `DeviceContext` class, `__post_init__` guard — `src/domain/entities/device_context.py:46-69` | HAZARD-PROTO-001 (RMF-001 §3.C — Closed, Mitigated) | `tests/integration/test_hl7v2_adapter.py` (vendor-specific parsing cases) |

### 3.2 Vital Sign Domain Entity

| Requirement | Design Artifact | Hazard Link | Test |
|---|---|---|---|
| REQ-VITAL-001 | `VitalSignType(str, Enum)` — `src/domain/entities/vital_sign.py:16-24` | HAZARD-NEWS2-001 (RMF-001 §3.A — Closed, Mitigated) | `tests/regulatory/test_news2_safety.py`; `tests/unit/test_news2_calculator.py` |
| REQ-VITAL-002 | `VitalSignSample` — `@dataclass(frozen=True)`, `src/domain/entities/vital_sign.py:66-72` | Immutability control (ISO 14971 general note, no single hazard ID cited in source) | Structural (`frozen=True`); exercised implicitly by `tests/integration/*`, `tests/unit/test_signal_processor_edge_cases.py` |
| REQ-VITAL-003 | `VitalSignSample.__post_init__` — `src/domain/entities/vital_sign.py:89-104` | HAZARD-PROTO-002 (RMF-001 §3.C — **Open, Requires Action**; post-mitigation Prob/Risk-Index genuinely blank) | `tests/unit/test_signal_processor_edge_cases.py::TestSamplingRateExtremesOrchestrator::test_negative_sampling_rate_rejected_at_entity_construction` |

### 3.3 Patient Context

| Requirement | Design Artifact | Hazard Link | Test |
|---|---|---|---|
| REQ-CTX-001 | `PatientContext` class — `src/domain/entities/patient_context.py:32-38` | HAZARD-SPO2-001 (RMF-001 §3.A — Closed, Mitigated) | `tests/unit/test_news2_calculator.py::TestSpO2Scale1Scoring` / `::TestSpO2Scale2Scoring` |

### 3.4 HL7 v2.x Adapter

| Requirement | Design Artifact | Hazard Link | Test |
|---|---|---|---|
| REQ-HL7-001 | `HL7v2Adapter.parse()` try/except around `hl7apy` parse call — `src/infrastructure/adapters/hl7v2_adapter.py:269-273` | Fail-fast boundary; not itself a registered `HAZARD-*` ID in RMF-001 (SRS-001 notes it is "distinct from HAZARD-WAVE-001") | `tests/integration/test_hl7v2_adapter.py::test_invalid_hl7_raises_value_error` |
| REQ-HL7-002 | `HL7v2Adapter._parse_obx()` OBX-11 status gate — `src/infrastructure/adapters/hl7v2_adapter.py:385,404-413` | HAZARD-BOUNDS-001-adjacent per SRS-001; HAZARD-BOUNDS-001 itself is RMF-001 §3.A, Closed, Mitigated | `tests/integration/test_hl7v2_adapter.py::test_x_status_obx_is_skipped` |
| REQ-HL7-003 | `_safe_field()` module function — `src/infrastructure/adapters/hl7v2_adapter.py:788-798` | Fail-isolated philosophy shared with HAZARD-PROTO-001 (Closed, Mitigated) per SRS-001; not independently registered | `tests/integration/test_hl7v2_vendor_edge_cases.py` (malformed/truncated MSH-3 cases, indirect coverage per SRS-001) |

### 3.5 DSP Pipeline

| Requirement | Design Artifact | Hazard Link | Test |
|---|---|---|---|
| REQ-PROC-001 | `ProcessedVitalSign` — `@dataclass(frozen=True)`, `src/domain/services/signal_processor.py:48-53` | HAZARD-ARCH-001 (RMF-001 §3.A — Closed, Mitigated) | `tests/regulatory/test_hazard_arch_001_pipeline_order.py` |

### 3.6 NEWS2 Scoring

| Requirement | Design Artifact | Hazard Link | Test |
|---|---|---|---|
| REQ-NEWS2-001 | `NEWS2Score` class (`src/domain/entities/news2_score.py:46-54`); `NEWS2Calculator.calculate()` (`src/domain/services/news2_calculator.py`, docstring at 82) | HAZARD-NEWS2-001 (RMF-001 §3.A — Closed, Mitigated) | `tests/regulatory/test_news2_safety.py::TestHazardNEWS2001ScoringAccuracy` |
| REQ-NEWS2-002 | `NEWS2Score._validate_component_ranges()` — `src/domain/entities/news2_score.py:79-101` | HAZARD-NEWS2-002 (RMF-001 §3.A — Closed, Mitigated) | `tests/regulatory/test_news2_safety.py::TestHazardNEWS2002RiskLevel` |
| REQ-NEWS2-003 | `NEWS2InsufficientDataError` (`news2_calculator.py:36-42`); `NEWS2Calculator._assert_required_parameters_present()` (`news2_calculator.py:130-153`) | HAZARD-NEWS2-003 (Closed, Mitigated) + HAZARD-DSP-007 (RMF-001 §3.B — **Open, INTERIM engineering sign-off only**) | `tests/unit/test_news2_calculator.py::TestInsufficientDataHandling`; `tests/integration/test_api_vitals.py::TestVitalsHazardDsp007NanExcludedNotOpaqueFailure` |

### 3.7 FHIR Output

| Requirement | Design Artifact | Hazard Link | Test |
|---|---|---|---|
| REQ-FHIR-001 | `BundleAssembler.assemble()` per-Observation try/except (`bundle_assembler.py:109-115`); `BundleAssembler._build_error_entry()` (`bundle_assembler.py:198-207`) | Availability control, reinforces HAZARD-DSP-007's response-shape principle per SRS-001; not independently registered as its own hazard ID | `tests/integration/test_fhir_bundle.py` |

### 3.8 API / Cross-Cutting

| Requirement | Design Artifact | Hazard Link | Test |
|---|---|---|---|
| REQ-API-001 | `value_error_handler()` — `src/main.py:217-238` | Information-disclosure control; not independently registered as a `HAZARD-*` ID | `tests/integration/test_api_ingest.py::TestIngestErrorHandling` |
| REQ-API-002 | `unhandled_exception_handler()` — `src/main.py:240-267` | Same information-disclosure control as REQ-API-001 | `tests/integration/test_main_exception_handler.py::TestReqApi002NoLeakOnUnhandledException` — **added this session** (see §6; previously no dedicated test existed for this exact guarantee, as SRS-001 §6 and RMF-001 both already flagged) |
| REQ-API-003 | `health_check()` — `src/api/v1/health.py:59-66` | Operational/availability requirement, not a clinical-scoring hazard control | `tests/integration/test_api_health.py::TestHealthEndpoint` (13 tests) |
| REQ-API-010 | `VitalSignPayload(BaseModel)` — `src/api/v1/vitals.py:45-50` | HAZARD-DSP-007 (Open, INTERIM sign-off only) — SRS-001 explicit: this requirement's statement does **not** claim NaN/Infinity exclusion; actual mitigation is downstream in `PhysiologicalBoundsChecker`, not this Pydantic model | `tests/integration/test_api_vitals.py::TestVitalsValidationErrors` |

**§3 row count: 17** (one per `REQ-*` ID; matches SRS-001 §3's 17-requirement count exactly).

## 4. Test Citation Verification Log

Every class/function name cited in §3's Test column was checked to exist, this session, by
`grep`ing the actual test file (not re-trusting SRS-001's prior citation):

| Citation | File | Verified at line |
|---|---|---|
| `test_invalid_hl7_raises_value_error` | `tests/integration/test_hl7v2_adapter.py` | 352 |
| `test_x_status_obx_is_skipped` | `tests/integration/test_hl7v2_adapter.py` | 336 |
| `TestSpO2Scale1Scoring` / `TestSpO2Scale2Scoring` | `tests/unit/test_news2_calculator.py` | 109 / 138 |
| `TestSamplingRateExtremesOrchestrator::test_negative_sampling_rate_rejected_at_entity_construction` | `tests/unit/test_signal_processor_edge_cases.py` | 159 / 178 |
| `TestHazardNEWS2001ScoringAccuracy` / `TestHazardNEWS2002RiskLevel` | `tests/regulatory/test_news2_safety.py` | 84 / 135 |
| `TestInsufficientDataHandling` | `tests/unit/test_news2_calculator.py` | 302 |
| `TestVitalsHazardDsp007NanExcludedNotOpaqueFailure` | `tests/integration/test_api_vitals.py` | 316 |
| `TestIngestErrorHandling` | `tests/integration/test_api_ingest.py` | 293 |
| `TestHealthEndpoint` | `tests/integration/test_api_health.py` | 15 |
| `TestVitalsValidationErrors` | `tests/integration/test_api_vitals.py` | 446 |
| `TestReqApi002NoLeakOnUnhandledException` (new) | `tests/integration/test_main_exception_handler.py` | 54 |

All 17 `src/` `REQ-*` tag locations were independently re-confirmed by `grep -rno
"REQ-[A-Z0-9-]*" src/` this session (17 unique IDs, matching SRS-001's count exactly — no drift
between SRS-001's compilation and this one).

## 5. Item 2 — REQ-API-002 No-Leak Test (added this session, not documentation-only)

**Gap, as flagged independently by both SRS-001 §6 and RMF-001:** the previously-existing
`tests/integration/test_api_ingest.py::test_error_response_has_detail_field` accepts either a
422 or a 500 outcome and only asserts a `detail` key is present — it does not exercise the
catch-all `unhandled_exception_handler` specifically, and does not assert non-leakage of
exception type/message/traceback.

**Closed this session:** `tests/integration/test_main_exception_handler.py` (new file, 3 tests)
— installs a throwaway route that raises a non-`ValueError` exception carrying a deliberately
sensitive-looking message, drives it through the real ASGI app/middleware stack via
`httpx.ASGITransport(..., raise_app_exceptions=False)`, and asserts:

1. The HTTP response body is the exact generic envelope
   (`{"error": "internal_server_error", "detail": "An unexpected error occurred..."}`)
   and contains none of: the exception type name (`RuntimeError`), the exception message, or
   Python traceback markers (`Traceback`, `File "`).
2. Response headers likewise carry none of the above.
3. **Mutation-tested this session, then reverted**: `src/main.py`'s handler was temporarily
   edited to return `str(exc)` as the `detail` field; the new test failed as expected (caught
   the leak), confirming the test is not a tautology. The mutation was reverted immediately
   after (`git diff --stat src/main.py` confirmed a clean revert to the committed state).
4. A companion test confirms the *other* half of REQ-API-002's statement — that the exception
   IS still logged server-side at ERROR level with `exc_type`/`error` populated (via
   `structlog.testing.capture_logs()`) — so the no-leak fix is verified not to have silently
   traded away server-side observability.

**Full regression suite re-run after adding this test:** 661 passed, 1 xfailed (658 → 661; the
3 new tests), 95% overall coverage, `src/main.py` coverage 96% → 99%. No regressions.

## 6. Phase 5-Stream Layer — "Hazard-Tracked, Requirement-Tracking Not Yet Applied" (§2 decision, applied)

No `REQ-*` rows exist for this layer (confirmed: `grep -rno "REQ-[A-Z0-9-]*"
src/infrastructure/streaming/ src/infrastructure/provisioning/` returns zero matches). What
**does** exist, re-verified this session directly against source:

| Hazard ID | Source location | In Risk Register (`ICU_Edge_Gateway_Risk_Register_2.xlsx`)? |
|---|---|---|
| HAZARD-STREAM-001 | `src/infrastructure/streaming/mllp_listener.py:23` | **Yes, as of 2026-08-10 (this session, follow-up)** — row 40, `Open - Deferred by Scope Decision`, unscored. Was register-absent when this matrix was first compiled earlier the same day; see §6.1 below. |
| HAZARD-STREAM-002 | `src/infrastructure/streaming/ring_buffer.py:12` (its defining anchor; also referenced from `live_dashboard_channel.py:39` and `mqtt_publisher.py:39`) | **Yes, as of 2026-08-10** — row 41, `Open - Deferred by Scope Decision`, unscored. |
| HAZARD-STREAM-003 | `src/infrastructure/streaming/mqtt_publisher.py:23` | **Yes, as of 2026-08-10** — row 42, `Open - Deferred by Scope Decision`, unscored. |
| HAZARD-STREAM-004 | `src/infrastructure/streaming/mqtt_publisher.py:47` | **Yes, as of 2026-08-10** — row 43, `Open - Deferred by Scope Decision`, unscored. |
| HAZARD-STREAM-005 | `src/infrastructure/streaming/live_dashboard_channel.py:18` | **Yes, as of 2026-08-10** — row 44, `Open - Deferred by Scope Decision`, unscored. |
| HAZARD-STREAM-006 | `src/infrastructure/streaming/subscription_dispatcher.py:30` | Yes — row 31, Open/PROPOSED pending sign-off |
| HAZARD-STREAM-007 | `src/infrastructure/streaming/subscription_registry.py:27` | Yes — row 32, Open/PROPOSED pending sign-off |
| HAZARD-STREAM-008 | `src/infrastructure/streaming/subscription_dispatcher.py:35` | Yes — row 33, Open/PROPOSED pending sign-off |
| HAZARD-STREAM-009 | `src/api/v1/fhir_subscription.py:21`; `src/config.py:152` | Yes — row 34, Open/mitigation applied, not self-closed |
| HAZARD-STREAM-010 | `src/infrastructure/provisioning/bootstrap.py:52` | Yes — row 35, Open/PROPOSED, CA-pinning mitigation narrows scope |
| HAZARD-STREAM-011 | `src/infrastructure/provisioning/cert_store.py:13` | Yes — row 36, Open/PROPOSED, scheduling gap closed |
| HAZARD-STREAM-012 | `src/infrastructure/provisioning/enrollment_client.py` (cross-reference comment added 2026-08-10, this session — see §6.2) — full hazard record remains `infra/terraform/modules/ca/main.tf:13-43`, not `src/` | Yes — row 38, Open/INTERIM engineering sign-off recorded 2026-08-10 |
| HAZARD-DSP-007 | `src/infrastructure/streaming/mqtt_publisher.py:260` | Yes — row 39 (cross-cutting; also linked from REQ-NEWS2-003/REQ-API-010 above) |
| HAZARD-ARCH-001 | `src/infrastructure/streaming/mllp_listener.py:17` | Yes — row 22, Closed, Mitigated (cross-cutting reference from streaming into an already-closed core hazard) |

**Finding at original compilation, resolved same day (§6.1):** HAZARD-STREAM-001 through -005
existed as `PROPOSED` hazard commentary directly in source but did **not** appear anywhere in
the Risk Register when this matrix was first built. Rows were added this session (see §6.1) —
this table reflects the post-fix state; the original gap is preserved in the row history for
audit purposes, not silently edited away.

**Conclusion for this layer, current state:** hazard-tracked (12 of 12 source-tagged hazards
trace to a source location; all 12 now also trace into the Risk Register). Requirement-tracking
still not applied (0 `REQ-*` rows, by the §2 decision above — unchanged).

### 6.1 Register Update (this session, follow-up to original compilation)

Per explicit follow-up instruction, HAZARD-STREAM-001 through -005 were added as Risk Register
rows:

- **Backup taken first**, per this workbook's established convention:
  `ICU_Edge_Gateway_Risk_Register_2.backup-20260810e-pre-stream001-005-add.xlsx`.
- **Content transcribed from the source docstrings** (`mllp_listener.py`, `ring_buffer.py`,
  `mqtt_publisher.py` ×2, `live_dashboard_channel.py`) at the register's existing column
  granularity — not invented. Verification Evidence cells cite test files/classes confirmed
  this session to exist and to exercise the named mitigation (e.g.
  `tests/integration/test_mllp_listener.py::TestOversizedFrameRejected`,
  `tests/unit/test_ring_buffer.py::TestOverflowDropOldest`) — except HAZARD-STREAM-004, where no
  dedicated test for the TLS-disabled-warning path was found (`grep -in "tls"
  tests/unit/test_mqtt_publisher.py` — zero matches), recorded as `N/A` rather than assumed
  covered.
- **Status:** `Open - Deferred by Scope Decision` for all five — matching Process Items
  PROC-002's existing status wording exactly, not the requesting instruction's paraphrase of it,
  to keep the register's status vocabulary consistent with its own established convention.
- **Sev/Prob/Risk Index columns left blank**, matching the register's own stated rule (RMF-001
  §3: "A blank Sev/Prob/Risk Index means the source workbook has never scored that entry —
  shown as blank here too, not defaulted to 0 or 1") — entry as a row is not risk evaluation.
- **Process Items PROC-002 updated for consistency**, not left stale: its Status changed from
  `Open - Deferred by Scope Decision` to `Closed - Entered as Register Rows`; its Description
  had an `UPDATE 2026-08-10` note appended (original text preserved, not overwritten — same
  preserve-the-record convention RMF-001 §9 used for the HAZARD-CORS-001 gap).

**Self-flagged discrepancy found while doing this, not previously stated anywhere:** the Risk
Register's actual pre-edit row count was **35**, not the 34 RMF-001 states ("34 hazard
entries... every row currently in the workbook, not a curated subset" — RMF-001 front matter;
**correction below** — SRS-001 does not independently assert a hazard-entry count at all, so
this was RMF-001's inaccuracy alone, not a two-document one; the original phrasing of this note
was itself wrong and is corrected here in the same spirit as everything else this matrix
self-flags). The 35th row is `(unassigned -- awaiting Risk ID)` (a PVC/`storageClassName`
finding about `cert_store.py`'s device-key storage, explicitly not yet assigned a `HAZARD-*` ID
per a prior project-owner instruction) — it has no `HAZARD-*` ID, so it was excluded from
RMF-001's per-hazard-ID enumeration, but it IS a populated row in the actual workbook.

**UPDATE 2026-08-10 (later same day, follow-up task):** RMF-001 has since been corrected —
"34" → "40" throughout (front matter, §2.1, §3 module tables, §4, §5, §6, §9), and the
previously-unenumerated row added to both §3.F and Appendix A under the placeholder reference
`UNASSIGNED-PVC-001` (RMF-001's own front-matter correction note explains the placeholder). Every
count in RMF-001 was re-verified row-by-row against the actual workbook this same follow-up
(exact ID-list diff between RMF-001's `####` Appendix A headings, RMF-001's §3 summary-table
rows, and the workbook's `Risk ID` column — all three sets match exactly, 40 entries each). This
matrix's own count in §1/§6 above already matched the corrected 40; no change was needed here
beyond this note and the Hazard Link row's count reference (§1).

### 6.2 HAZARD-STREAM-012 Bidirectional Traceability (this session, follow-up)

Previously (original compilation): HAZARD-STREAM-012 had a full hazard record in
`infra/terraform/modules/ca/main.tf:13-43` and a Risk Register row, but **zero** presence in
`src/` — a register/design-doc-to-source dead end for a Python-code reader.

**Added this session:** a cross-reference comment in
`src/infrastructure/provisioning/enrollment_client.py`, at the exact line where the device
places its cryptographic root of trust (`verify=ca_bundle_path if ca_bundle_path else True` in
`DeviceEnrollmentClient.__init__`) — the one place in `src/` where this hazard's subject (trust
in the CA) is actually exercised. The comment names HAZARD-STREAM-012, states its fleet-wide
scope in one sentence, and points to `infra/terraform/modules/ca/main.tf`'s existing docstring
as the full record — **it does not restate or rewrite that docstring**, per instruction.

This closes the "register entry has no source anchor at all" gap. It does **not** add a new
Risk Register row (per the follow-up instruction's own framing — the hazard's register row
already existed; only its source-traceability was missing).

## 7. Self-Flagged Gaps (this document)

- **Phase 5-Stream layer has zero `REQ-*` rows** — by explicit decision, §2 above, not an
  oversight. Unchanged by this session's follow-up work (§6.1/§6.2), which closed the
  hazard-*tracking* gaps for this layer, not the requirement-tracking one — that decision stands.
- **~~HAZARD-STREAM-001 through -005 were source-only~~ — RESOLVED 2026-08-10 (§6.1):** added as
  Risk Register rows, entry only (not risk evaluation — Sev/Prob remain unscored). Left here,
  struck through, as a record that the gap existed and was closed, not deleted without a trace.
- **~~RMF-001's "34 hazard entries" claim was inaccurate~~ — RESOLVED 2026-08-10 (follow-up
  task, same day):** the register actually had 35 populated rows even before this session's 5
  additions (the PVC/`storageClassName` finding carried no `HAZARD-*` ID and was excluded from
  RMF-001's per-ID count). Register total is now 40. RMF-001 has since been corrected throughout
  (front matter, §2.1, §3, §4, §5, §6, §9) and the previously-unenumerated row added as
  `UNASSIGNED-PVC-001`; re-verified row-by-row (ID-list diff), not by arithmetic. See §6.1's
  update note.
- **Several §3 rows have no independently-registered `HAZARD-*` ID** (REQ-VITAL-002, REQ-HL7-001,
  REQ-HL7-003, REQ-FHIR-001, REQ-API-001, REQ-API-002) — SRS-001 already described these as
  general ISO 14971 controls or hazard-adjacent, not as pointing to a specific register row;
  this matrix carries that same distinction forward rather than inventing a hazard ID to fill
  the column.
- **REQ-VITAL-002's/REQ-HL7-001's/REQ-HL7-003's Hazard Link cells are the weakest links in this
  matrix** — they describe a control rationale in prose (from SRS-001) rather than a checkable
  register ID, so they cannot be cross-verified the same way the other rows' hazard links were.
- **~~HAZARD-STREAM-012 had no source-code tag at all~~ — RESOLVED 2026-08-10 (§6.2):** a
  cross-reference comment was added in `enrollment_client.py`, pointing to
  `infra/terraform/modules/ca/main.tf`'s existing full docstring rather than duplicating it.
- **No credentialed CSO reviewed this matrix, the Risk Register edit, or the source cross-
  reference** — same standing gap as SRS-001/RMF-001; the `Open - Deferred by Scope Decision`
  status on the five new rows and the interim sign-off on HAZARD-STREAM-012 are both
  engineering-only determinations, not clinical risk judgments.

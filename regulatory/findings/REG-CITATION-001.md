# REG-CITATION-001 — FDA CDS Non-Device Exemption Citation Appears Incorrect

**Status:** 🔶 **PROPOSAL — AWAITING HUMAN REGULATORY / LEGAL SIGN-OFF**
**Raised:** 2026-08-21
**Raised by:** Engineering (automated codebase audit)
**Disposition:** **NOT SELF-CERTIFIED.** No code has been changed. This document
exists to be reviewed by whoever owns regulatory affairs for this product. Do not
action it as a find-and-replace.

**Severity rationale:** the disputed citation is not confined to internal
documentation. It is **embedded in the FHIR `Observation.note` text emitted to every
downstream consumer**, so it can reach a hospital's clinical record and an EMR
vendor's integration surface. A wrong regulatory citation travelling into a clinical
record is materially worse than a wrong comment in a source file.

---

## 1. The current citation

Nine words, emitted verbatim in production output:

> `FDA CDS Non-Device Exemption applies (21 CFR §880.3780).`

Source: [`src/infrastructure/fhir/news2_builder.py:217`](../../src/infrastructure/fhir/news2_builder.py#L217)

A second, differently-worded citation also exists:

> `FDA CDS: Entities represent the clinical information layer per 21 CFR Part 880.3.`

Source: [`src/domain/entities/vital_sign.py:6`](../../src/domain/entities/vital_sign.py#L6)

These are **two different claims** (`§880.3780` vs `Part 880.3`) and should be
reconciled together, not separately.

---

## 2. Why the citation appears to be wrong

**The CDS carve-out is statutory, not a device classification regulation.** A
21 CFR Part 880 citation points into the *classification* regulations for general
hospital and personal use devices — a fundamentally different instrument from the
statutory exclusion that removes qualifying CDS software from the definition of a
device in the first place.

The exclusion derives from:

| Layer | Reference |
|---|---|
| Statute | FD&C Act **§ 520(o)(1)(E)** |
| U.S. Code | **21 U.S.C. § 360j(o)** |
| Enacted by | 21st Century Cures Act **§ 3060(a)** (2016) |
| FDA interpretation | FDA guidance, *Clinical Decision Support Software* |

**This finding is not new to this codebase.** It was independently reached during an
earlier review and is already recorded, unresolved, in:

- [`docs/REG-001_Intended_Use_and_CDS_Exemption_Draft.md` §B.1](../../docs/REG-001_Intended_Use_and_CDS_Exemption_Draft.md)
  — *"This citation could not be verified and should be checked against your
  regulatory counsel's records before further use."*
- [`docs/PROJECT_HANDOFF_SUMMARY.md`](../../docs/PROJECT_HANDOFF_SUMMARY.md) lines
  114–117 and 211, which flag it for correction.

REG-CITATION-001 does not supersede REG-001; it supplies the **exhaustive location
inventory and blast-radius analysis** that REG-001 did not have, so the correction can
actually be executed once counsel decides the wording.

### What engineering could NOT verify here

Stated plainly rather than glossed:

- **We did not confirm what 21 CFR §880.3780 actually designates**, or whether it
  exists. No authoritative CFR source was consulted from this environment. It is
  possible the number is a transcription error for something the regulatory function
  is legitimately tracking. That reconciliation is counsel's, not engineering's.
- **`claude/verified_claims_sheet.md` does not exist in this repository.** It was
  named as the source of truth for approved wording. The replacement wording in §3
  below is therefore **engineering's proposal, not approved language**, and is
  explicitly flagged as such. If an approved claims sheet exists elsewhere, its
  wording supersedes §3 entirely.
- The regulatory-update context in §6 was **supplied to engineering by the project
  owner** and is recorded here as received. It has not been independently verified
  against a primary FDA source from this environment.

---

## 3. Proposed replacement wording (ENGINEERING PROPOSAL — NOT APPROVED)

Two options, because the right answer depends on a decision only counsel can make:
**whether this product is asserting the exemption, or merely designed toward it.**

### Option A — Cite the statute, keep the assertion (minimal change)

> `NEWS2 score calculated per RCP 2017 guidelines. This is a clinical decision`
> `support advisory output only. Independent clinician review is required before any`
> `action. Intended to meet the CDS exclusion criteria of FD&C Act §520(o)(1)(E)`
> `(21 U.S.C. §360j(o)).`

Note the softening from **"Exemption applies"** to **"Intended to meet … criteria."**
This matters: *"applies"* is a legal conclusion the software cannot reach on its own,
and REG-001 §B.2 already found that the exemption must be evaluated **per software
function**, with at least one function in this product (waveform DSP) plausibly
falling outside the exclusion. A blanket "applies" is therefore a stronger claim than
the existing analysis supports.

### Option B — Drop the regulatory conclusion from emitted output entirely

> `NEWS2 score calculated per RCP 2017 guidelines. This is a clinical decision`
> `support advisory output only. Independent clinician review is required before any`
> `action.`

**Engineering's recommendation is Option B for the *emitted* string**, with the
regulatory analysis living in `docs/REG-001` where it can be versioned, reviewed and
corrected without redeploying the gateway or reissuing Bundles. The advisory-only
substance — which is what actually protects the patient and the reader — is fully
preserved. A citation in a clinical record cannot be corrected once it has been
filed by a receiving system.

The machine-readable advisory flag is unaffected either way: the extension
`https://samd.icu-edge/fhir/extensions/cds-advisory-only` (`valueBoolean: true`) and
the `X-CDS-Advisory-Only: true` response header carry no CFR reference and need no
change.

---

## 4. Exhaustive location inventory

### 4a. EMITTED — reaches consumers outside this repository (URGENT SET)

| # | Location | Emitted where | Contains number? |
|---|---|---|---|
| E1 | `src/infrastructure/fhir/news2_builder.py:217` | **`Observation.note[].text` in every FHIR Bundle** — REST responses, WebSocket deltas, MQTT telemetry, FHIR Subscription rest-hook deliveries | ✅ `21 CFR §880.3780` |
| E2 | `src/main.py:189` | OpenAPI `info.description`, served at `/openapi.json`, `/docs`, `/redoc` | ❌ label only |
| E3 | `Dockerfile:62` | OCI image label `samd.regulatory.fda="CDS-Non-Device"` — visible via `docker inspect` | ❌ label only |
| E4 | `docs/API-001_OpenAPI_Specification.json:5` | Exported spec artifact shared with EMR/integration partners | ❌ label only |
| E5 | `docs/API-001_OpenAPI_Specification.yaml:8` | Same, YAML form | ❌ label only |

**E1 is the urgent one.** It is the only emitted location carrying the disputed
number, and it is the only one that can be persisted into a patient's clinical record
by a receiving system.

E2–E5 assert the *label* "FDA CDS Non-Device Exemption" without a citation. They are
still an unqualified regulatory claim about the whole product, which REG-001 §B.2
found unsupportable product-wide — a separate but related issue.

### 4b. DEMONSTRATION LAYER — displayed on screen, not part of the SaMD

| # | Location | Notes |
|---|---|---|
| D1 | `demo/dashboard.py:294` | Permanent header banner, contains `21 CFR §880.3780` |
| D2 | `demo/dashboard.py:646` | Sidebar regulatory badge, label only |

Outside `src/`, excluded from the container image, not part of the Class B software
item — but shown to prospects during demonstrations, so it carries the claim to an
audience regardless of its regulatory scope.

### 4c. INTERNAL DOCUMENTATION — does not leave the repository

| Location | Form |
|---|---|
| `src/domain/services/news2_calculator.py:15` | `FDA CDS Non-Device Exemption (21 CFR §880.3780)` — **has the number** |
| `src/domain/entities/vital_sign.py:6` | `21 CFR Part 880.3` — **different citation, also disputed** |
| `src/domain/entities/news2_score.py:11` | label only |
| `src/api/v1/ingest.py:15` | label only |
| `src/api/v1/fhir_subscription.py:16` | label only |
| `src/infrastructure/fhir/news2_builder.py:15, 115, 205` | label only |
| `README.md:9, 205` | already carries a caveat against treating it as settled |
| `docs/SRS-001…md:24`, `docs/RMF-001…md:25–27`, `docs/REG-001…md` (multiple), `docs/PROJECT_HANDOFF_SUMMARY.md:106–117, 171, 211`, `docs/ICU_Edge_Gateway_Phase5_Technical_Package.md:91`, `docs/ICU_Edge_Gateway_OnePager_Content.md:103` | analysis / caveats |

Note: `src/domain/services/news2_calculator.py` and `src/domain/entities/*` are under
the **frozen clinical-algorithm constraint**. Even a docstring-only correction there
should be raised as its own change with its own review, not folded into a bulk edit.

### 4d. TEST FIXTURES

`tests/fixtures/live_deltas.json` lines 660, 1936, 2680 contain the full emitted note
text, because these fixtures were **captured from a live gateway** rather than
hand-authored. They are snapshots of real output; they will need recapturing after any
change to E1, but they assert nothing about the citation (see §5).

---

## 5. Which tests assert on the affected strings

**Answer: none of them assert the citation. Changing it breaks no test.**

Verified individually:

| Test | What it actually asserts | Breaks on change? |
|---|---|---|
| `tests/integration/test_fhir_bundle.py:322` `test_note_contains_advisory_text` | `"advisory" in all_notes.lower()` | ❌ No — the word "advisory" survives both Option A and Option B |
| `tests/integration/test_api_ingest.py:167` | `x-cds-advisory-only == "true"`; the phrase appears only in the **assertion failure message** | ❌ No |
| `tests/integration/test_api_vitals.py:218` | Same pattern — header value, phrase only in the failure message | ❌ No |
| `tests/unit/test_dashboard_logic.py` | Reads `live_deltas.json`, but asserts on `Bundle.note` (pipeline warnings) and component codes — never the `Observation.note` advisory text | ❌ No |

Worth noting for the reviewer: the FDA advisory note lives on the **NEWS2
`Observation`**, whereas DSP pipeline warnings live on the **`Bundle`**. They are
different `note` arrays. The dashboard's artifact panel reads the Bundle one, so it
never displays the citation.

---

## 6. Separate item — FDA CDS guidance update, January 2026

*Recorded as received from the project owner; not independently verified from this
environment.*

FDA's *Clinical Decision Support Software* guidance was **updated on 15 January
2026** — after the code carrying these citations was written. Two consequences worth
separating:

**6a. Criterion 3 relaxed for single-recommendation outputs.** NEWS2 produces exactly
one score, which is precisely the single-recommendation shape the update addresses.
This may be *favourable* to the exemption analysis in REG-001, which was written
against the earlier interpretation. REG-001's Criterion-3 reasoning should be re-run
against the current text rather than assumed still valid.

**6b. Explicit expectation of clinical-validity evidence.** The update is understood
to add an expectation that developers hold evidence of clinical validity for
single-recommendation outputs. That is an **evidence-generation obligation, not a
citation fix**, and it does not currently have an owner on this project. Relevant
existing assets: `tests/regulatory/test_news2_safety.py` and
`tests/regulatory/test_hazard_dsp_007_nan.py` establish *algorithmic conformance to
the RCP 2017 specification* — they are not clinical-validity evidence, and should not
be offered as such.

**Recommendation:** raise 6b as its own tracked item. Conflating "our citation is
wrong" with "we owe clinical-validity evidence" would let the second, much larger
obligation ride along invisibly behind a one-line string change.

---

## 7. Blast radius of making the change

**Low technical risk, non-trivial regulatory consequence.**

| Dimension | Assessment |
|---|---|
| Tests | **Zero break.** See §5. |
| ASGI contract | Unaffected. No path, status, header or media type changes. `X-CDS-Advisory-Only` is untouched. |
| FHIR conformance | Unaffected. `Observation.note[].text` is free text; no profile constrains its content. |
| Downstream consumers | **Text-diff visible.** Any consumer string-matching this note breaks — but such a consumer is already relying on undocumented free-text and is out of contract. |
| Already-issued Bundles | **Not retroactively fixable.** Bundles emitted before the change keep the old citation wherever they were persisted. This is the strongest argument for Option B and for acting promptly. |
| Frozen domain code | `news2_calculator.py:15` and `vital_sign.py:6` are docstring-only, but sit under the no-edit constraint — separate change, separate review. |
| Test fixtures | `live_deltas.json` needs recapturing after an E1 change. Mechanical. |
| Demo layer | `demo/dashboard.py:294` should track whatever E1 becomes, so the screen and the wire agree. |

---

## 8. Requested decision

Engineering is **not** proceeding without these answers:

1. **Is `21 CFR §880.3780` wrong, or does it refer to something regulatory affairs is
   tracking that engineering is unaware of?**
2. **Option A (cite the statute) or Option B (remove the regulatory conclusion from
   emitted output)?** Engineering recommends **B for E1**, on the grounds that an
   emitted citation cannot be recalled once persisted downstream.
3. **Should "Exemption applies" become "intended to meet the criteria of"?**
   REG-001 §B.2 found the blanket product-wide assertion unsupportable.
4. **Does an approved claims sheet exist?** If so, its wording supersedes §3 and
   engineering will use it verbatim.
5. **Who owns item 6b** (clinical-validity evidence under the January 2026 guidance)?

Until answered, the citation stays exactly as it is. A wrong citation left visible and
formally tracked is safer than a plausible-looking citation silently substituted by
engineering without authority to make the determination.

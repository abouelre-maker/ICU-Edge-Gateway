# API Quickstart — ICU Edge-to-FHIR Interoperability Gateway

> **Evidence basis.** Every example, header and payload shape below was
> captured from a running instance of this gateway on 2026-08-21, not written
> from the source and hoped to be accurate. Where something was not observed,
> it says so.
>
> **Approved claims come from [`claude/verified_claims_sheet.md`](../../claude/verified_claims_sheet.md).**
> That sheet is the source of truth for every factual and regulatory statement
> here. Each statement below also cites the repository artefact or observed run
> that supports it. Treat unattributed marketing language as absent by design.

---

## Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Component health, version, uptime |
| `/api/v1/ingest` | POST | Raw HL7 v2.x ORU^R01 → FHIR R4 Bundle |
| `/api/v1/vitals` | POST | Structured JSON vitals → FHIR R4 Bundle |
| `/api/v1/fhir/Subscription` | GET, POST | FHIR R4 Subscription management |
| `/api/v1/fhir/Subscription/{id}` | GET, DELETE | Single subscription |
| `/api/v1/live/vitals` | **WebSocket** | Live delta stream (see below) |
| `localhost:2575` | **MLLP over TCP** | HL7 v2.x, the protocol bedside monitors speak |

Interactive documentation:

- Swagger UI — <http://localhost:8000/docs>
- ReDoc — <http://localhost:8000/redoc>
- OpenAPI JSON — <http://localhost:8000/openapi.json>
- Offline copy — [`docs/demo/openapi.json`](openapi.json) (OpenAPI 3.1.0, exported from a running instance)

> **The WebSocket route is deliberately absent from `openapi.json`.** OpenAPI
> 3.1 has no WebSocket vocabulary and FastAPI does not emit one, so
> `/api/v1/live/vitals` is documented here rather than in the spec. Do not
> read its absence as the route not existing.

---

## `GET /health`

```bash
curl -s http://localhost:8000/health
```

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime_seconds": 73.4,
  "components": {
    "hl7v2_adapter":    { "status": "healthy" },
    "dsp_pipeline":     { "status": "healthy" },
    "news2_calculator": { "status": "healthy" },
    "fhir_builder":     { "status": "healthy" }
  }
}
```

Returns **200** when every component is healthy, **503** when degraded — so it
is usable directly as a container/orchestrator liveness probe.

---

## `POST /api/v1/ingest` — raw HL7 v2.x

Accepts an ORU^R01 as `text/plain`. Segments must be **CR-terminated**
(`\r`), not LF — this is HL7, not a text file.

### Query parameters

| Parameter | Required | Values | Notes |
|---|---|---|---|
| `spo2_scale` | yes | `SCALE_1`, `SCALE_2` | **Clinician decision.** `SCALE_2` only for patients with a prescribed 88–92% target (e.g. hypercapnic COPD). ISO 14971 HAZARD-SPO2-001: never infer this from SpO2 values. |
| `encounter_id` | no | string | FHIR `Encounter/{id}` reference |
| `device_vendor` | no | `PHILIPS`, `GE`, `DRAEGER`, `MINDRAY`, `NIHON_KOHDEN`, `GENERIC` | **Omit to auto-detect from MSH-3.** There is no `auto` value; sending one returns **422**. |
| `device_model` | no | string | e.g. `IntelliVue MX800` |
| `device_id` | no | string | FHIR `Device/{id}` reference |

### Example — Philips proprietary OBX-3 codes

```bash
printf 'MSH|^~\\&|PHILIPS_INTELLIVUE|ICU_UNIT|EHR|HOSPITAL|20260821120000||ORU^R01|QS1|P|2.5.1\r'  >  msg.hl7
printf 'PID|1||PT-DEMO-001^^^HOSP^MR||DEMO^SYNTHETIC||19700101|U\r'                                >> msg.hl7
printf 'OBR|1||ORDER-QS1|||||20260821120000\r'                                                     >> msg.hl7
printf 'OBX|1|NM|HR^Heart Rate^PHILIPS||72|/min|||||F|||20260821120000\r'                          >> msg.hl7
printf 'OBX|2|NM|RESP^Respiration Rate^PHILIPS||16|/min|||||F|||20260821120000\r'                  >> msg.hl7
printf 'OBX|3|NM|SPO2^Arterial Oxygen Saturation^PHILIPS||98|%%|||||F|||20260821120000\r'          >> msg.hl7
printf 'OBX|4|NM|NIBP-S^Non-Invasive Systolic^PHILIPS||120|mmHg|||||F|||20260821120000\r'          >> msg.hl7
printf 'OBX|5|NM|TEMP^Temperature^PHILIPS||37.0|Cel|||||F|||20260821120000\r'                      >> msg.hl7
printf 'OBX|6|NM|57834-7^Oxygen therapy^LN||0||||||F|||20260821120000\r'                           >> msg.hl7
printf 'OBX|7|ST|76270-8^AVPU score^LN||A||||||F|||20260821120000\r'                               >> msg.hl7

curl -s -D - -X POST 'http://localhost:8000/api/v1/ingest?spo2_scale=SCALE_1' \
     -H 'Content-Type: text/plain' --data-binary @msg.hl7
```

The same gateway accepts GE CARESCAPE LOINC codes and Dräger proprietary
codes (`RR`, `NBP-S`, `T1`) without configuration — vendor is detected from
MSH-3. See `scripts/demo_inject.py` for all three dialects.

**AVPU must be sent as `ST`, not `NM`.** A numeric AVPU value is skipped and
the consciousness parameter is lost.

---

## `POST /api/v1/vitals` — structured JSON

Same pipeline, JSON input. `spo2_scale` is a **body** field here, not a query
parameter.

```bash
curl -s -X POST http://localhost:8000/api/v1/vitals \
  -H 'Content-Type: application/json' -d '{
    "patient_id": "PT-DEMO-002",
    "spo2_scale": "SCALE_2",
    "samples": [
      {"vital_sign_type":"RESPIRATORY_RATE","value":18,"unit":"breaths/min","timestamp":"2026-08-21T12:00:00Z"},
      {"vital_sign_type":"SPO2","value":90,"unit":"%","timestamp":"2026-08-21T12:00:00Z"},
      {"vital_sign_type":"SYSTOLIC_BP","value":125,"unit":"mmHg","timestamp":"2026-08-21T12:00:00Z"},
      {"vital_sign_type":"HEART_RATE","value":78,"unit":"bpm","timestamp":"2026-08-21T12:00:00Z"},
      {"vital_sign_type":"TEMPERATURE_CELSIUS","value":36.9,"unit":"Cel","timestamp":"2026-08-21T12:00:00Z"},
      {"vital_sign_type":"SUPPLEMENTAL_O2","value":1,"unit":"bool","timestamp":"2026-08-21T12:00:00Z"}
    ]}'
```

Sending that payload with `SCALE_2` and again with `SCALE_1` returns totals of
**2 (LOW)** and **5 (MEDIUM)** respectively — observed, not computed for this
document. That three-point difference on identical physiology is why the scale
is a required, explicit parameter.

---

## Response-header contract

Present on **both** ingest endpoints:

| Header | Example | Notes |
|---|---|---|
| `X-CDS-Advisory-Only` | `true` | Always `true`. Advisory-only output. |
| `X-Pipeline-Duration-Ms` | `1.69` | Domain pipeline duration for this request |
| `X-Warning-Count` | `0` | Number of pipeline warnings (see `Bundle.note`) |
| `X-NEWS2-Total` | `0` | **Omitted** when no score could be produced |
| `X-NEWS2-Risk-Level` | `NORMAL` | `NORMAL`, `LOW`, `LOW_MEDIUM`, `MEDIUM`, `HIGH`. **Omitted** with the total. |
| `Content-Type` | `application/fhir+json` | |

> **Two traps, both hit during development.**
>
> 1. **uvicorn emits header names lower-cased.** Matching `X-NEWS2-Total`
>    case-sensitively silently misses every time. Compare case-insensitively.
> 2. **Absent ≠ zero.** When a NEWS2-mandatory parameter is rejected or
>    missing, the score is withheld and the two `X-NEWS2-*` headers are
>    **omitted entirely**. `0` is a valid NEWS2 total, so defaulting a missing
>    header to `0` turns "no score" into "perfectly well".

---

## FHIR R4 Bundle response (trimmed)

Observed shape: `Bundle` of type `collection`, **9 entries** for a full
seven-parameter message — one `Device`, seven vital-sign `Observation`s, and
the NEWS2 `Observation`.

```jsonc
{
  "resourceType": "Bundle",
  "type": "collection",
  "entry": [
    { "resource": { "resourceType": "Device", "id": "DEVICE-PHILIPS", "...": "..." } },

    { "resource": {
        "resourceType": "Observation",
        "status": "final",
        "code": { "coding": [
          { "system": "http://loinc.org", "code": "8867-4", "display": "Heart rate" },
          { "system": "http://snomed.info/sct", "code": "364075005" }
        ]},
        "subject": { "reference": "Patient/PT-DEMO-001" },
        "valueQuantity": { "value": 72.0, "unit": "bpm", "system": "http://unitsofmeasure.org", "code": "/min" }
    }},

    // ... five further vital-sign Observations ...

    { "resource": {
        "resourceType": "Observation",
        "status": "final",
        "category": [{ "coding": [{ "code": "survey", "display": "Survey" }]}],
        "code": { "coding": [
          { "system": "http://snomed.info/sct", "code": "1239842005",
            "display": "National Early Warning Score 2 (assessment scale)" }
        ]},
        "subject": { "reference": "Patient/PT-DEMO-001" },
        "valueInteger": 0,
        "interpretation": [{ "coding": [{ "code": "N", "display": "Normal" }]}],
        "extension": [
          { "url": "https://samd.icu-edge/fhir/extensions/news2-risk-level", "valueCode": "NORMAL" },
          { "url": "https://samd.icu-edge/fhir/extensions/iec62304-software-version", "valueString": "1.0.0" },
          { "url": "https://samd.icu-edge/fhir/extensions/cds-advisory-only", "valueBoolean": true }
        ],
        "component": [
          { "code": { "coding": [{ "code": "9279-1"  }, { "code": "86290005"  }]}, "valueInteger": 0 },
          { "code": { "coding": [{ "code": "59408-5" }, { "code": "431314004" }]}, "valueInteger": 0 },
          { "code": { "coding": [{ "code": "57834-7" }, { "code": "371825009" }]}, "valueInteger": 0 },
          { "code": { "coding": [{ "code": "8480-6"  }, { "code": "271649006" }]}, "valueInteger": 0 },
          { "code": { "coding": [{ "code": "8867-4"  }, { "code": "364075005" }]}, "valueInteger": 0 },
          { "code": { "coding": [{ "code": "67775-7" }, { "code": "248234008" }]}, "valueInteger": 0 },
          { "code": { "coding": [{ "code": "8310-5"  }, { "code": "276885007" }]}, "valueInteger": 0 }
        ],
        "note": [{ "text": "NEWS2 score calculated per RCP 2017 guidelines. ..." }]
    }}
  ]
}
```

### Integration notes worth knowing before you write a parser

- **Locate the NEWS2 Observation by SNOMED `1239842005`.** Its `component[]`
  entries reuse the same LOINC codes as the vital-sign Observations, so
  filtering on LOINC alone will confuse the two.
- **Consciousness has different codes in and out.** The adapter *accepts*
  LOINC `76270-8` ("AVPU score") on input but *emits* `67775-7` ("Level of
  responsiveness"). Assuming the input code silently drops the seventh
  component — a real bug found during development.
- **Every component carries both a LOINC and a SNOMED coding.** Match on
  either.
- **`Bundle.note[]` carries DSP pipeline warnings** (rejected artifacts). The
  advisory note lives on the NEWS2 **Observation**, not the Bundle. Different
  arrays; do not conflate.
- **A rejected reading is present, not absent.** Out-of-bounds observations
  appear with `dataAbsentReason` = `out-of-range` and no `valueQuantity`.
  Render that as "rejected", not as a gap.

> **Regulatory note.** The CFR citation formerly embedded in
> `Observation.note[].text` has been **removed** from emitted output
> (REG-CITATION-001 E1); the note now carries only the RCP 2017 attribution and
> the advisory-only statement shown above. Verified in
> [`evidence/mllp_smoke_100.txt`](evidence/mllp_smoke_100.txt), which records
> the distinct emitted note text across 100 messages and an explicit
> `'880.3780' present: False` check. The wider citation question remains open —
> see [`regulatory/findings/REG-CITATION-001.md`](../../regulatory/findings/REG-CITATION-001.md).
> Do not string-match against the note text.
>
> The gateway's regulatory posture, stated in full and approved wording:
>
> The gateway is engineered under IEC 62304 Class B software life-cycle practices with ISO 14971 risk
> analysis applied to each hazard, and is designed against the non-device clinical decision support
> criteria in FD&C Act §520(o)(1)(E) as interpreted by FDA's Clinical Decision Support Software
> guidance. Output is advisory only and requires independent clinician review; the software triggers
> no automated treatment. These are the developer's own determinations and have not been reviewed by
> FDA or any notified body.


---

## WebSocket — `ws://localhost:8000/api/v1/live/vitals`

No query parameters, no authentication, no subprotocol. Every connected
client receives every delta for every patient; demultiplex by `patient_id`.

**Push-only. There is no snapshot frame on connect** — a newly connected
client sees nothing until the next message is ingested. This is by design, not
a defect.

Exactly one frame type is emitted:

```jsonc
{
  "type": "vitals.delta",
  "source": "mllp",                    // or "http-ingest" | "http-vitals"
  "received_at": "2026-08-21T12:16:24.892361Z",
  "patient_id": "PT-DEMO-001",         // "UNKNOWN" if not extractable
  "news2": { "total": 0, "risk_level": "NORMAL" },   // null when no score
  "bundle": { /* the full FHIR R4 Bundle above */ }
}
```

- `news2` is **`null`** when the pipeline could not produce a score. Handle
  it; do not assume the object exists.
- `news2` carries **only** `total` and `risk_level`. The seven components are
  in `bundle`.
- There is **no heartbeat frame**. Detect staleness by timing your own
  arrivals.

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://localhost:8000/api/v1/live/vitals") as ws:
        async for raw in ws:
            d = json.loads(raw)
            n = d.get("news2") or {}
            print(d["patient_id"], n.get("total"), n.get("risk_level"))

asyncio.run(main())
```

---

## MLLP — `localhost:2575`

The protocol real bedside monitors and interface engines speak. Disabled by
default; enable with `MLLP_ENABLED=1` (`MLLP_HOST`, `MLLP_PORT` also
available).

Framing: `0x0B` **message** `0x1C` `0x0D`. Frames over 1 MiB are rejected;
stray bytes before a start block are discarded and logged.

Acknowledgements:

```
MSH|^~\&|ICU-EDGE-GATEWAY|EDGE|||20260821120000||ACK|ACK20260821120000|P|2.5.1
MSA|AA|ACK20260821120000|
```

- `AA` accepted, `AE` on decode/parse failure. `AR` is never emitted.
- **MSA-2 echoes the gateway's own generated control ID, not your MSH-10.**
- There is **no `ERR` segment**; the reason goes in MSA-3.
- A malformed message NAKs **without dropping the connection**.
- The ACK carries **no NEWS2 score** — read the WebSocket or use HTTP if you
  need the result.

> **MLLP applies one process-wide SpO2 scale** (`SCALE_1` by default) to every
> message. HL7 v2.x has no field for scale assignment and this gateway does
> not infer one, because that is a clinician decision (HAZARD-SPO2-001). For
> per-patient scale, use the HTTP endpoints where it is explicit. A
> clinician-facing scale registry consulted by the listener is on the roadmap;
> it is **not implemented**.

---

## Errors

| Status | Cause |
|---|---|
| 200 | Success — including a degraded score with warnings in `Bundle.note` |
| 422 | Invalid query/body parameter (e.g. `device_vendor=auto`) |
| 500 | Unhandled error. The response body deliberately omits exception type, message and traceback (IEC 62304 REQ-API-002); the detail is in the server log. |

A message whose NEWS2-mandatory parameter is rejected still returns **200**
with a Bundle — the other observations are present, `Bundle.note` explains the
rejection, and the `X-NEWS2-*` headers are omitted. A degraded but honest
response, not an error.

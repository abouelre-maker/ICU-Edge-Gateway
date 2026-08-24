# Module 1 — Outreach Kit — 2026-08-23

**Gate status: CLEARED 2026-08-23.** `run_demo.bat` ran end to end on the Windows machine — status
badge LIVE, ~85 msg/min, all three bed cards updating. The Loom can be recorded.

**One constraint carried forward.** That was a single run on one laptop. Do not quote ~85 msg/min, or
any latency figure, as a system capability — no load test has been run. The sayable claim is "the
stack runs end to end and I have seen it"; nothing more.

**Audience.** Vendor-side technical buyers — CTO / VP Engineering / Chief Architect at EMR
integrators, patient-monitoring OEMs, and clinical-analytics vendors. These are Model A (IP buyout)
and Model B-via-partner counterparties. This kit is **not** written for hospital CIOs/CMIOs; that
audience needs an entity, SOC 2, and insurance behind you first.

---

## 1. Loom script — 90 seconds, word for word

Speak at a normal pace. Do not rush the evidence section; it is the part that earns the second call.
Screen: dashboard visible from 0:20, terminal with test output from 1:00.

---

**[0:00 – 0:12] — Cold open, screen on the bed wall**

> I'm Housam Ashraf, a biomedical engineer. This is an ICU edge gateway I built and verified end to end.
> Ninety seconds — HL7 in, FHIR out, and the evidence behind it.

**[0:12 – 0:28] — The problem**

> Bedside monitors stream continuously, but that data rarely reaches the EMR in a structured form.
> And the alarms that do fire are often sensor noise, not deterioration. That's the alarm-fatigue
> problem, and it's a data-quality problem before it's a clinical one.

**[0:28 – 0:52] — The pipeline, live**

> Three beds here, three different vendors — Philips proprietary codes, GE with LOINC, Dräger — all
> normalizing with no per-vendor configuration. That's HL7 v2.5.1 over MLLP, real framing, real
> acknowledgements.
>
> Watch this bed. NEWS2 climbs zero, three, six, seven, seventeen as the sepsis scenario develops.
> Deterministic RCP 2017 scoring, all seven parameters.
>
> And this one — heart rate out of physiological bounds. The gateway marks it rejected and shows
> **no score**. It does not fabricate a reassuring zero. That distinction is the whole point.

**[0:52 – 1:08] — The output**

> Every score leaves as a FHIR R4 Bundle — dual LOINC and SNOMED coding, UCUM units, the NEWS2
> Observation coded SNOMED 1239842005. Your EMR ingests it without custom mapping work.

**[1:08 – 1:24] — The evidence, screen on test output**

> Eight hundred sixteen tests passing, ninety-four point six percent coverage, confirmed in CI, not
> on my laptop. Every NEWS2 scoring boundary tested at the exact threshold. Forty-two tests just for
> non-finite value rejection — eighteen of them fail against the pre-fix code, which is how I know
> they're load-bearing and not decorative.

**[1:24 – 1:30] — The honest close**

> What this is: a verified reference implementation, engineered under IEC 62304 Class B practices,
> advisory output only. What it isn't: cleared, deployed, or run against real patient data — not
> yet. If that's a gap you're already equipped to close, let's talk.

---

**Word count ≈ 235.** If you run long, cut the [0:12 – 0:28] problem block to one sentence — a
vendor-side CTO already knows the problem. Never cut the [1:24] close.

---

## 2. Cold outreach — email template

**Subject line options** (A/B these; keep them flat and specific, no hype):

- `HL7 v2.5.1 to FHIR R4 gateway with NEWS2 — verified reference implementation`
- `ICU edge gateway IP — 816-test evidence trail, available for license`
- `Question about your HL7 ingestion path`

**Body:**

> Hi [First name],
>
> I'm a biomedical engineer. I built and verified an ICU edge gateway: HL7 v2.5.1 over MLLP in,
> artifact rejection, deterministic NEWS2 scoring, FHIR R4 Bundles out — with dual LOINC/SNOMED
> coding, so it lands in an EMR without custom mapping.
>
> I'm reaching out to [Company] specifically because [one concrete, researched reason — e.g. "your
> monitoring line already speaks HL7 but I couldn't find a NEWS2 path in your published docs", or
> "you integrate with Epic on the analytics side and this sits directly upstream of that"].
>
> What I think is worth your time isn't the feature list — it's the evidence trail. 816 automated
> tests passing at 94.6% coverage, CI-confirmed. Every NEWS2 boundary tested at the exact threshold.
> Engineered under IEC 62304 Class B practices with ISO 14971 risk analysis.
>
> Equally, what it is not: no FDA clearance, no real patient data, no production deployment. It's a
> verified reference implementation and an IP asset — built for a partner who already has the
> compliance infrastructure to take it the rest of the way.
>
> If that's interesting, I have a 90-second walkthrough and can share the architecture under NDA.
> Worth a short call?
>
> Housam Ashraf
> Biomedical Engineer & HealthTech Solutions Architect
> housam@[your-domain] · linkedin.com/in/housam-abouelreish-805352226

---

### Why this template is shaped this way

- **The disclosure paragraph is the differentiator, not a liability.** Every inbound pitch a vendor
  CTO receives overclaims. Volunteering the gaps in paragraph four is what makes paragraphs one
  through three credible. Do not remove it to sound stronger — it is the strongest part.
- **The `[one concrete, researched reason]` bracket is mandatory.** An email without it is a mass
  mail and will be read as one. If you cannot fill it in from ten minutes of research on that
  company, do not send to that company.
- **The ask is a call, not a deck.** Asking for a call converts; asking someone to review an
  attachment does not.
- **No attachment on the first email.** The one-pager goes out on reply, not cold — cold attachments
  hurt deliverability and read as spray-and-pray.

---

## 3. Follow-up cadence

| Touch | Timing | Content |
|---|---|---|
| 1 | Day 0 | Email above |
| 2 | Day 4 | Reply in-thread. One new concrete fact, e.g. the SpO₂ Scale 1 vs Scale 2 three-point swing. Two sentences. |
| 3 | Day 11 | LinkedIn connection request, no pitch in the note — just "reached out by email about the ICU gateway, happy to send the walkthrough if useful." |
| 4 | Day 21 | Final in-thread reply: "closing the loop — if the timing isn't right, no problem. Happy to reconnect when it is." Then stop. |

Four touches, then stop. A fifth costs you the relationship for later.

---

## 4. Next steps, in order

1. **Get a professional email on a domain you control.** This is the single highest-leverage item in
   the whole kit and it costs about $12/year. A student or personal Gmail address in the signature
   undoes the credibility that 816 tests earned. Do this before any outreach.
2. **Clear the Windows Live Demo Gate.** Run the patched `run_demo.bat`, confirm the bed wall
   renders, then record the Loom.
3. **Build the target list — 25 companies, not 250.** EMR integrators, patient-monitoring OEMs,
   clinical-analytics vendors. For each: the specific technical reason you're contacting them. If
   you can't write that sentence, drop the company.
4. **Send in batches of 5**, four days apart. Track reply rate per subject line. Adjust after the
   first 15.
5. **Start the US entity formation in parallel** — not after the first interested reply. The bank
   account is the long pole for a non-resident founder, and you do not want a warm counterparty
   waiting on it.
6. **Have counsel lined up before, not after, a term sheet.** M&A/IP counsel and a cross-border tax
   advisor. You do not need to retain them today; you need to know who you would call.

---

**Claims discipline reminder.** Every factual statement in this kit traces to
`claude/verified_claims_sheet.md`. If you edit any of it, re-check against that sheet first. The
forbidden list stands: FDA-approved, FDA-cleared, certified, compliant (unqualified), validated
(unqualified), production-ready, HIPAA-compliant.

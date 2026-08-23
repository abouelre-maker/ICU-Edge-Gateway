# Three-Minute Demonstration Script

**Audience:** hospital CIO / CMIO / EMR integration lead
**Runtime:** 3 minutes
**Pre-flight:** [`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md) — do it before the room fills, not in it.

> **Say "synthetic" in the first thirty seconds and mean it.** Every patient on
> screen is generated. The banner says so permanently. A clinical audience will
> respect the distinction and stop trusting you if you blur it.
>
> **Do not say:** "FDA-approved", "FDA-cleared", "certified", "compliant",
> "validated" unqualified, or "production-ready". None of those are true, and a
> CMIO will know. What *is* true is specific and stronger — use it.

---

## Before you start

`run_demo.bat` (Windows) or `./run_demo.sh` (macOS/Linux). Wait for the boxed
summary. Browser opens at `http://localhost:8501`.

**Leave the dashboard on screen for ~10 seconds before you speak.** You want
the grey **AWAITING FIRST MESSAGE** state visible — it is a talking point,
not an embarrassment.

---

## 0:00 – 0:20 — The problem

**Click:** nothing. Dashboard on screen, AWAITING or just-populated.

**Say:**

> "Your ICU monitors speak HL7 v2 — a 1980s pipe-delimited format. Your EMR
> wants FHIR R4. Today that gap is closed by a custom integration project per
> vendor, per unit, that someone has to maintain forever.
>
> This is that gap closed once. Three different monitor vendors are about to
> appear on this screen. None of them were configured individually."

**If the beds are already populated:** skip ahead — say "and they're already
here", and move to 0:20.

**If it says AWAITING FIRST MESSAGE:** use it —

> "That grey badge is honest engineering. This is a push stream with no
> snapshot on connect, so until a monitor sends something, we show you nothing
> rather than something stale."

---

## 0:20 – 1:00 — Three vendors, normalised live

**Click:** point at the three bed cards, left to right.

**Say:**

> "Bed 1 is a Philips IntelliVue, sending proprietary codes — `HR`, `RESP`,
> `NIBP-S`. Bed 2 is a GE CARESCAPE sending LOINC. Bed 3 is a Dräger, using a
> *different* proprietary dialect again — `RR`, `NBP-S`, `T1`.
>
> Same gateway, no per-vendor configuration. Vendor is detected from the
> message header. Every one of them comes out the other side as FHIR R4 with
> the same coding."

**Point at the `via mllp` chip on each card:**

> "And that's over MLLP — raw TCP, the protocol the monitors actually speak.
> Not a file drop, not a nightly batch."

**Recovery — a bed missing:** the streamer sends every 2 s. Wait one beat. If
a bed is still absent, say "that one's mid-cycle" and continue; do **not**
restart anything mid-demo.

**Recovery — DISCONNECTED (red):** say "the feed's dropped — watch, it
reconnects on its own", and continue talking. It backs off and recovers
without intervention. If it does not recover in ~30 s, see the runbook.

---

## 1:00 – 1:40 — Deterioration, and *why*

**Click:** point at **ICU-BED-03**. Its NEWS2 total is climbing.

**Say:**

> "Bed 3 is a scripted sepsis deterioration. Watch the score.
>
> Normal. Low. Medium. High — and the card goes red."

**The ramp holds each stage for about twenty seconds.** That is deliberate, so
each band is readable. **It is not frozen.** If someone asks, say so.

**Click:** the **NEWS2 component breakdown** panel on Bed 3.

**Say:**

> "This is the part that matters clinically. It isn't just a number going up —
> respiratory rate is contributing 3, systolic pressure 3, heart rate 3. A
> clinician can see *which* physiology is driving the score without opening
> the chart.
>
> That's the four-to-six hour window before an arrest. It's the window NEWS2
> exists to buy you."

**Then, as it climbs to 17:**

> "And there's the consciousness parameter — new confusion. Three points on
> its own under RCP 2017, regardless of cause."

**Recovery — Bed 3 sitting at 0:** the loop is 90 seconds and restarts at
baseline. Say "it's just cycled — it climbs again in a moment" and use the
time to open the FHIR panel (2:20 beat) early, then come back.

---

## 1:40 – 2:20 — Clinical depth competitors skip

### The SpO2 scale comparison

**Scroll to:** *SpO2 Scale 1 vs Scale 2 — what-if analysis*.
**Click:** **Run comparison on ICU-BED-02's current vitals**.

**Say:**

> "Bed 2 is a COPD patient on oxygen, sitting at 90 percent saturation. On the
> standard scale that's a three-point penalty. On Scale 2 — the scale you
> actually prescribe for a hypercapnic patient — it's zero.
>
> Same patient. Same reading. Two versus five. That crosses a risk band: low
> becomes medium, and someone gets called who didn't need to be."

**Point at the caption:**

> "Both of those numbers came back from the gateway's calculator. This isn't
> the screen recolouring a number — it posted the vitals twice and asked.
>
> And note what we *don't* do: the scale is never inferred from the SpO2
> value. It's a clinician's decision, it's an explicit parameter, and HL7 v2
> has nowhere to carry it — which is exactly why this comparison runs over the
> REST API and not the monitor feed."

### The rejected artifact

**Click:** if a bed shows a **REJECTED** vital, point at it. Otherwise run in
a second terminal:

```
venv311\Scripts\python scripts\demo_inject.py --scenario artifact --transport http
```

**Say:**

> "That's a 450 beats-per-minute reading — a lead artifact. The signal
> processing rejected it before scoring.
>
> Look at what the score does: it doesn't show zero. It shows **NO SCORE**.
> Heart rate is mandatory for NEWS2, so rather than quietly scoring the
> patient as well, it declines to score at all and tells you why.
>
> Every one of those is an alarm that never reached a nurse."

### The subtle one — if you have a CMIO in the room

```
venv311\Scripts\python scripts\demo_inject.py --scenario low-medium --transport http
```

**Say:**

> "Respiratory rate of 8. Total score of 3 — which sounds reassuring.
>
> But it's amber, not green, and it says one-hourly observations. Because a
> *single* parameter scoring 3 escalates on its own, whatever the total. Most
> implementations of NEWS2 get that wrong. Bed 3 is also on 3 right now and
> it's green — same number, different response."

*(Reference: `docs/demo/screenshots/07-low-medium-single-parameter-rule.jpg`
shows both side by side.)*

---

## 2:20 – 2:50 — The interoperability proof

**Click:** **View FHIR R4 Bundle** on any bed.

**Say:**

> "This is what your EMR receives. FHIR R4, standard resources.
>
> The NEWS2 score is a SNOMED-coded Observation — 1239842005 — carrying all
> seven sub-scores as components, each with LOINC *and* SNOMED codings. Plus an
> extension marking it advisory-only.
>
> Your integration team writes no mapping layer for this. It's the standard,
> as published."

**Scroll to a vital-sign Observation:**

> "And the individual vitals are ordinary FHIR Observations with UCUM units.
> Nothing bespoke. Nothing you have to take on trust."

**Recovery — expander slow with large Bundles:** open it *before* you start
talking, while narrating the previous beat.

---

## 2:50 – 3:00 — The close

**Click:** the sidebar.

**Say:**

> "816 automated tests, including regulatory tests that lock the NEWS2
> boundaries against drift.
>
> To be straight with you: this is a verified reference implementation, not a
> cleared device. The regulatory pathway is documented and open — that's a
> conversation, not a checkbox.
>
> What I'd like is two hours with your integration team and one real monitor
> feed."

**If asked "is it FDA approved?" — answer "No", then give the approved wording.**

This paragraph is the *only* approved statement of regulatory posture
(`claude/verified_claims_sheet.md` §3). Say it as written; do not paraphrase it,
and do not cite a CFR number:

> The gateway is engineered under IEC 62304 Class B software life-cycle practices with ISO 14971 risk
> analysis applied to each hazard, and is designed against the non-device clinical decision support
> criteria in FD&C Act §520(o)(1)(E) as interpreted by FDA's Clinical Decision Support Software
> guidance. Output is advisory only and requires independent clinician review; the software triggers
> no automated treatment. These are the developer's own determinations and have not been reviewed by
> FDA or any notified body.

Then add: "one of our own citations is under review and the finding is open in
the repository — I'd rather show you the open file than claim a clearance we
don't have."

That answer wins more rooms than a confident overstatement, and it is the only
one that survives diligence.

---

## Screenshots

| File | Beat |
|---|---|
| `01-awaiting-first-message.jpg` | 0:00 |
| `02-bed-wall-live.jpg` | 0:20 |
| `03-bed-03-high-with-components.jpg` | 1:00 |
| `04-rejected-artifact-and-stale.jpg` | 1:40 |
| `05-spo2-scale-comparison.jpg` | 1:40 |
| `06-disconnected-gateway-down.jpg` | recovery |
| `07-low-medium-single-parameter-rule.jpg` | 1:40 |

All captured from real runs on 2026-08-21.

---

## If everything breaks

Close the browser and talk over the screenshots. They are real captures of
this system, and every number in this script came from an observed run — you
are not fabricating anything by presenting them. Then book the follow-up.

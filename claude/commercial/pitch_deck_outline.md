# B2B Technical Pitch Deck — 10-Slide Outline

**Owner:** Eng. Housam Ashraf — Biomedical Engineer & HealthTech Solutions Architect
**Use:** second-call deck, screen-shared, 20 minutes with 10 for questions.
**Not for:** cold outreach. Cold gets the one-pager and the Loom; the deck is earned.

---

## Design constraints before you build a single slide

- **One idea per slide.** If a slide needs a second heading, it is two slides.
- **The evidence is the aesthetic.** No stock photos of doctors, no gradient hero shots. Numbers,
  diagrams, and a screenshot of the real bed wall. Buyer-side CTOs discount decks that look like
  marketing and lean in on decks that look like engineering.
- **Dark theme, matching the dashboard** (`#0e1117` canvas, `#161b22` panels, `#e6edf3` text). Your
  product already has a visual identity; use it.
- **Every claim traceable** to `claude/verified_claims_sheet.md`. If a slide asserts something not in
  that sheet, cut the claim or cut the slide.

---

## Slide 1 — Title

- **ICU Edge Gateway**
- Subtitle: *Verified reference implementation — HL7 v2.5.1 to FHIR R4 with deterministic NEWS2*
- Eng. Housam Ashraf · Biomedical Engineer & HealthTech Solutions Architect
- Contact + LinkedIn
- Footer: *Confidential — prepared for [Company]. Not for redistribution.*

Personalise the footer per company. It signals this is not a mass deck.

---

## Slide 2 — The problem, in their language

Three lines, no paragraph:

- Bedside monitors stream continuously; structured data rarely reaches the EMR.
- Alarms fire on sensor noise as often as on deterioration.
- Deterioration scoring is manual, delayed, or inconsistent across shifts.

**Speaker note:** with a vendor-side CTO, spend 30 seconds here maximum. They know the problem. The
slide exists so you and they agree on the frame before you show the solution.

---

## Slide 3 — The pipeline

The Mermaid data-flow diagram from `architecture_and_ux_spec.md` §1, rendered.

Call out the **dotted rejection branch** verbally: out-of-bounds produces `NO SCORE`, never a
reassuring zero.

**This is the technical hook slide.** If they are going to lean forward, it happens here.

---

## Slide 4 — Live bed wall

Full-bleed screenshot of the running three-bed dashboard. Minimal annotation — two callouts at most:

- the NEWS2 score climbing on the sepsis bed,
- the `REJECTED / NO SCORE` card.

**Speaker note:** if the Loom is recorded, offer to play 20 seconds of it instead. Motion beats a
screenshot for this specific slide.

---

## Slide 5 — The clinical logic that is hard to get right

The NEWS2 routing diagram (§2 of the architecture spec).

Two claims, both checkable:

- **SpO₂ Scale 1 vs Scale 2** — same patient, same vitals: 2 LOW versus 5 MEDIUM. A three-point swing
  across a risk band, verified live over HTTP.
- **LOW-MEDIUM band** — single parameter scoring 3 with total under 5 still escalates to hourly
  observation. Most naive implementations collapse this into LOW and hide the patient the rule exists
  to catch.

**Speaker note:** this is your credibility slide. A clinical lead in the room will recognise
immediately that you understand NEWS2 rather than having transcribed a table.

---

## Slide 6 — FHIR R4 output

A real, syntactically complete Bundle excerpt — not pseudo-JSON.

Annotate: dual LOINC + SNOMED coding, UCUM units, NEWS2 Observation coded SNOMED CT 1239842005, seven
scored components.

**The commercial line:** *ingests into an EMR without custom mapping work.* That sentence is the
integration cost you are removing from their roadmap, and it is what their VP Engineering is actually
pricing.

---

## Slide 7 — Evidence

Four numbers, large, no prose:

- **816 / 1** tests passing / xfailed — CI-confirmed
- **94.6%** statement coverage — CI-measured
- **6 phases** zero-regression
- **42** non-finite-value rejection tests, **18** of which fail against pre-fix code

**Speaker note:** the fourth number is the one that lands. It proves the tests are load-bearing rather
than decorative, and it is a claim almost no counterparty can make about their own suite. Say it
slowly.

---

## Slide 8 — What this is, and what it is not

Two columns, side by side, equal visual weight.

**Is:** verified reference implementation and IP asset. IEC 62304 Class B life-cycle practices. ISO
14971 risk analysis per hazard. Designed against the non-device CDS criteria in FD&C Act
§520(o)(1)(E). Advisory output only.

**Is not:** FDA cleared. Clinically validated. Deployed. Run against real patient data. Security
hardened. Under 150 MB.

**Do not soften this slide, and do not bury it at the end as a disclaimer.** Placing it before the
ask, at full size, is what makes slides 3 through 7 believable. Buyers have sat through a hundred
decks that overclaimed. The one that volunteers its own gaps is the one they trust — and the gaps are
work their organisation is already equipped to do, which is precisely why they are the buyer and you
are not.

---

## Slide 9 — Engagement models

Three columns, one line each — no numbers on the slide:

- **IP / source-code buyout** — asset purchase, full transfer, optional transition support.
- **Per-bed or per-site licence** — white-label or OEM into your existing compliant product.
- **Acquisition of the asset** — including founder transition.

**Speaker note:** pricing does not go on a slide. It goes in a conversation, after you have heard
their build-vs-buy estimate. If they ask on the call, the answer is: *"depends on structure — what
would it cost your team to build and validate this?"* Their answer is your anchor.

---

## Slide 10 — The ask

One sentence and a next step:

> *If this is a gap worth closing on your roadmap, the next step is a mutual NDA and read access to
> the repository — including the full 816-test manifest.*

Then: contact block, LinkedIn, and a single named next action with a date.

**Never end on "Thank you" or "Questions?".** End on the specific thing you want them to do.

---

## Appendix slides — hold in reserve, do not present

Have these loaded and jump to them only if asked:

- **A1** — Full test manifest excerpt (`pytest --collect-only`), the boundary tests visible.
- **A2** — CI run screenshot: Quality Gate green, Docker Verify green, the size gate honestly red.
- **A3** — Regulatory posture, full text of the §520(o)(1)(E) positioning paragraph.
- **A4** — Deployment topology and container posture (non-root uid 1001, healthy in 2 s).
- **A5** — Accessibility design: redundant shape markers and greyscale weights, and the two contrast
  values currently at AA-large with the proposed fix.
- **A6** — Open items register: GAP-DOCKER-SIZE-001, REG-CITATION-001, HAZARD-DSP-007, FLAKE-MQTT-001.

**A6 is a strength, not an exposure.** Producing a maintained defect register on request tells a
buyer-side architect that you track issues rather than discover them during diligence. Volunteer it
if the conversation is going well.

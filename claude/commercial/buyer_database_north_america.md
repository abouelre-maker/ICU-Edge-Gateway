# B2B Buyer Database — North America

**Owner:** Eng. Housam Ashraf
**Asset:** ICU Edge Gateway — HL7 v2.5.1/MLLP → artifact rejection → NEWS2 → FHIR R4
**Deal models in scope:** Model A (IP / source buyout) and Model B via partner sublicense.

---

## How to read this list

**Evidence status.** Company names, market positions, and product categories below are FACT — these
are well-established vendors in their segments, and the segment landscape was confirmed by search
during preparation. **Named individuals and their current titles are deliberately absent.** Personnel
data goes stale within months, and a wrong name in a cold email is worse than no name. You will source
the individual from LinkedIn Sales Navigator at send time — the *titles to search for* are given per
tier below, which is the durable part.

**Fit scores are INFERENCE** — my assessment of strategic fit based on each company's public product
posture, not on any inside knowledge of their roadmap or M&A appetite.

**This is a starting universe of ~30, not a send list.** Per the outreach kit: research each company
until you can write one specific sentence about why *them*. If you cannot write that sentence, drop
the company. A realistic first campaign is 20–25 companies.

---

## Tier 1 — Interoperability / integration-engine vendors

**Why this tier is first.** They already sell HL7-to-FHIR transformation into hospitals. Your gateway
is a clinical-logic layer sitting directly on top of the pipe they already own. The build-vs-buy
conversation is the easiest to have here, because they can price your asset against their own sprint
cost precisely.

| Company | Position | Fit | The angle |
|---|---|---|---|
| Redox | API-first interoperability platform, very large hospital connection footprint | High | They move data but stop short of clinical scoring. NEWS2 is a differentiating layer, not a competitor. |
| Rhapsody (incl. Corepoint / Lyniate lineage) | Major commercial integration engine | High | Deep HL7 v2 install base; a NEWS2 module is a natural upsell to existing customers. |
| InterSystems (HealthShare / IRIS for Health) | Interoperability platform + data fabric | Medium-High | Very capable in-house engineering; more likely to build. Still worth the conversation — they acquire selectively. |
| NextGen Healthcare (Mirth Connect) | Open-source-derived integration engine | Medium-High | Large Mirth community; a validated clinical channel is commercially interesting. |
| Health Gorilla | Interoperability / national network | Medium | Network-focused rather than edge-focused; fit depends on their clinical-data roadmap. |
| Zus Health | Modern health data platform | Medium | Developer-first; would evaluate the code seriously and quickly. |
| Particle Health | Health data API | Medium | Same profile as Zus — fast technical evaluation, smaller cheque. |
| 1upHealth | FHIR-native data platform | Medium | FHIR R4 output aligns exactly with their model. |

**Titles to search:** CTO · VP Engineering · Head of Interoperability · Director of Integration ·
Chief Architect · VP Product (Platform)

---

## Tier 2 — Patient monitoring / telemetry OEMs

**Why this tier matters most for valuation.** These companies own the bedside device that emits your
input. A NEWS2 layer is a software differentiator on hardware they already sell, and hardware vendors
historically pay more for software IP than software vendors do — because building it is further from
their core competency.

**Why it is slower.** Longer procurement, heavier legal, and a real possibility they route you to a
corporate-development process rather than an engineering one.

| Company | Position | Fit | The angle |
|---|---|---|---|
| Philips Healthcare (Patient Monitoring) | Market leader, IntelliVue | High value, slow | Largest install base emitting HL7. Approach via their venture/partnership arm, not cold to engineering. |
| GE HealthCare (Patient Care Solutions) | Major monitoring vendor | High value, slow | Same profile as Philips. |
| Drägerwerk | ICU-focused monitoring and ventilation | High | Strongly ICU-weighted — the closest segment match to your asset. |
| Mindray North America | Fast-growing challenger in US monitoring | High | Challenger vendors buy software differentiation to compete on capability rather than price. |
| Masimo | Patient monitoring, Root platform | Medium-High | Root is explicitly a third-party integration platform. |
| Nihon Kohden America | Monitoring, strong neuro/ICU presence | Medium-High | Similar challenger dynamic to Mindray. |
| Baxter / Hillrom (Welch Allyn) | Monitoring and connected care | Medium | Post-integration portfolio; appetite varies. |
| Spacelabs Healthcare | Monitoring, ICU and telemetry | Medium | Smaller and more approachable than the top three. |

**Titles to search:** VP Engineering · CTO · Director of Software / Digital Health · Head of
Connectivity · Director of Clinical Informatics · VP Corporate Development (for Philips/GE scale)

---

## Tier 3 — Clinical surveillance / deterioration-detection vendors

**Why this tier is real but narrow.** These companies do exactly what your asset does. That makes them
either the most natural acquirer or a direct competitor, depending on their build state. Approach with
the acquisition framing, not the partnership framing.

| Company | Position | Fit | The angle |
|---|---|---|---|
| Bernoulli Health / clinical surveillance vendors | Real-time clinical surveillance from device data | High | Directly adjacent; device-data surveillance is their core. |
| Etiometry | ICU data analytics, risk indices | High | ICU-native, analytics-native. Closest conceptual comparable. |
| Vitalchat / ambient ICU monitoring vendors | Virtual care and ICU observation | Medium | Fit depends on whether their roadmap includes scoring. |
| PeraHealth lineage (Rothman Index) | The canonical NEWS-adjacent deterioration index product | Reference | Named here as the closest market comparable for framing your pitch, not necessarily as a buyer. |

**Titles to search:** CTO · VP Engineering · Chief Medical Information Officer · Head of Data Science

---

## Tier 4 — RPM and virtual-care platforms

**Lowest priority.** Their data model is ambulatory and intermittent; yours is ICU and continuous.
The clinical logic does not transfer cleanly, and NEWS2 is not the standard scoring instrument in
their setting. Include a small number only if you have a specific reason.

| Company | Position | Fit |
|---|---|---|
| Biofourmis | RPM with acuity analytics | Medium — closest RPM fit, they do acuity |
| Current Health (Best Buy Health) | Hospital-at-home platform | Medium — hospital-at-home is the one RPM setting where deterioration scoring genuinely applies |
| Cadence, Optimize Health, HealthSnap | RPM platforms | Low — chronic-care model, wrong acuity |

**Titles to search:** CTO · VP Engineering · Head of Clinical Product

---

## Recommended send sequence

1. **Start with Tier 1.** Fastest technical evaluation, shortest path to a real conversation, and the
   feedback you get will sharpen your pitch before you spend your one shot at Tier 2.
2. **Then Tier 3.** Small, focused, high-conviction. These conversations will tell you what your asset
   is actually worth, because these buyers can price it against their own build.
3. **Then Tier 2** — once your pitch has survived contact with tiers 1 and 3. Do not open with Philips.
4. **Tier 4 only opportunistically.**

Batches of five, four days apart, per the cadence in the outreach kit.

---

## Sourcing the individual

For each target, at send time:

1. LinkedIn Sales Navigator → filter by company + the titles listed for that tier.
2. Prefer the most senior *engineering* title over the most senior title overall. A VP Engineering
   forwards to corp-dev; a CFO deletes.
3. Verify the person is currently there — check their post history, not just the profile header.
4. Find your one specific sentence: a conference talk, a job posting revealing their stack, a docs page
   that shows the gap your asset fills, a published integration list that omits NEWS2.
5. Only then write the email.

Company research that does not produce that sentence means the company is not a target yet.

---

**Sources consulted for the vendor landscape:**
[Top 12 Healthcare Interoperability Vendors](https://www.keragon.com/blog/healthcare-interoperability-vendors) ·
[Top Healthcare Interoperability & HIE Companies in the USA](https://www.capminds.com/blog/top-healthcare-interoperability-hie-companies-in-the-usa/) ·
[Best HL7 Integration Engines 2026](https://mirth.support/best-hl7-integration-engines-2026) ·
[Top 7 US Patient Monitoring Equipment Companies](https://idataresearch.com/news/us-patient-monitoring-equipment-companies/) ·
[Patient Monitoring Systems overview](https://umbrex.com/resources/industry-overviews/medical-device-industry-overviews/patient-monitoring-systems/)

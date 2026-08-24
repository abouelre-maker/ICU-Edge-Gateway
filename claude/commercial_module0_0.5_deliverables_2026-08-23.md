# Commercial Execution — Module 0 & 0.5 Deliverables — 2026-08-23

## Status
Windows Live Demo Gate logged as PENDING/UNCONFIRMED in `claude/engineering_phase_closure_2026-08-23.md` (item 5). Core engine (816/1 tests, CI-confirmed, 94.61% CI-measured coverage, merged via `c143037`) unaffected and independently verified — commercial preparation proceeds per founder's explicit instruction.

## Research constraint disclosed to founder
WebFetch hit a session rate limit during market research (5 parallel calls failed, reset ~14:10 UTC same day). WebSearch alone did not surface concrete published pricing for comparable clinical-decision-support / early-warning-score vendors (e.g., PeraHealth / Rothman Index). All pricing figures in the deliverables below are labeled INFERENCE or ASSUMPTION, never FACT, per the evidence-labeling discipline. They must be validated against real buyer conversations before use in a live negotiation.

## Market-fit critique — outcome
Delivered directly to the founder in conversation. Corrections made to prior GTM concepts:

- **Cross-border payment rails (Wise / Payoneer) — corrected.** Not viable for real enterprise B2B payments; no US enterprise AP or legal function will wire licensing revenue to a personal consumer account. A US entity (single-member LLC for pure licensing; Delaware C-Corp if acquisition is plausible) must exist before any definitive agreement. SWIFT wire *into that entity* under a signed agreement is standard and was never the problem.
- **Monetization path — reprioritized.** IP/asset licensing to an already-compliant partner, or an acqui-hire-style outcome, are the realistic near-term paths. Direct-to-hospital SaaS subscription is a later-stage goal, contingent on entity formation + SOC 2/HITRUST + cyber-liability insurance + GPO or reseller relationship — none of which exist today.
- **Outreach targeting — corrected.** Mid-size health systems (200–600 beds) rather than large IDNs, whose entrenched Epic/Cerner CDS modules and 6–18 month procurement cycles a pre-revenue, pre-entity founder cannot survive.
- **Kept:** Loom pitch, LinkedIn/email outreach, NDA-gated Cloudflare Tunnel demo (second-call technical walkthrough only, and only after the live-demo gate clears).
- **Market-database (X-ray) search** kept as one input only; KLAS Research, CB Insights / Rock Health, and HIMSS exhibitor lists recommended as higher-signal supplements.

## Deliverables produced

1. **`ICU_Edge_Gateway_Executive_One-Pager.pdf`** — single-page executive one-pager, sourced strictly from `claude/verified_claims_sheet.md`. Contains: problem statement, five capability pillars (condensed), evidence bar (816/1 tests, 94.6% coverage, NEWS2 0→3→6→7→17 trace, SpO₂ Scale 1 vs 2 three-point swing, zero-regression across six phases), verbatim §3 regulatory posture, "what this is / what it isn't" contrast, and engagement-model pointer.

2. **`ICU_Edge_Gateway_Pricing_Framework.docx`** — 8 sections plus cover. Evidence-tag legend (FACT / INFERENCE / ASSUMPTION); asset summary; three engagement models:
   - **Model A** — IP / source-code buyout via Asset Purchase Agreement. Indicative $120K–$450K lump sum plus optional milestone earn-out; all figures ASSUMPTION.
   - **Model B** — per-bed / per-site annual subscription, $45–$180/bed/month across three tiers; all ASSUMPTION; explicitly flagged as realistic near-term only via sublicense through an already-compliant partner, not direct-to-hospital.
   - **Model C** — SLA / support tiers at 15–35% of annual license fee; INFERENCE.
   Plus deal mechanics (US entity prerequisite, SWIFT payment mechanics, cross-border tax caveat directing to counsel, IP assignment scope checklist) and recommended sequencing.

Both verified against the claims sheet's forbidden-words list (FDA-approved, FDA-cleared, certified, production-ready, HIPAA-compliant, game-changing, revolutionary, seamless, cutting-edge) by direct source grep — zero occurrences outside explicit "this is NOT" / disclaimer framing. Both rendered to image and visually inspected page-by-page before delivery.

## Two founder-detail gaps flagged, not fabricated

1. **Contact email.** The only address on file is a university-student address (`hosamabualreesh@std.mans.edu.eg`), which undermines credibility with a US hospital-system buyer. The one-pager carries a bracketed placeholder — `[professional contact email — to be confirmed before external distribution]` — rather than the student address or an invented one. **Action required before external distribution.**
2. **Founder surname / background.** Only "Eng. Hossam — Biomedical Engineer & HealthTech Solutions Architect" was provided. Documents use this minimal, non-fabricated line. **Confirm or extend before external distribution.**

## Windows Live Demo Gate — root cause identified 2026-08-23

Diagnosed by reading `run_demo.bat` on the device. **The defect is in the launcher, not in the Python.** There is no `demo/app.py`; the dashboard is `demo/dashboard.py` and it is not implicated.

Two launcher defects, both in `run_demo.bat`:

1. **No `--server.address` on the Streamlit invocation (line 156).** Streamlit therefore binds `0.0.0.0`, which on first run triggers a Windows Defender Firewall prompt. If that prompt is dismissed or denied, the listener is blocked and every subsequent browser hit is refused.
2. **No readiness gate before the browser opens.** The gateway gets a proper blocking health gate (lines 133–151), but Streamlit gets only a fixed `ping -n 4 127.0.0.1` (~3 s) at line 157 before `start "" "http://127.0.0.1:%DASHBOARD_PORT%"` at line 164. Streamlit cold start on Windows — importing streamlit, pandas, and the 27 KB `dashboard_logic.py` — routinely exceeds 3 s, so the browser opens against a socket that is not yet listening.

Both symptoms present identically to the user as "the dashboard doesn't load."

**Fix applied to `run_demo.bat`:** added `--server.address 127.0.0.1` (loopback-only bind, no firewall prompt) and replaced the fixed delay with a polling readiness gate on the dashboard port.

**Gate remains PENDING until the founder runs it on Windows and confirms.** The fix could not be verified from this session: the device bridge exposes a Linux VM, not the Windows host, so the Windows-specific firewall and timing behaviour cannot be reproduced here.

## Open loose end carried over (non-blocking)
Whether `pytest-cov` was actually moved out of `requirements.txt` per the founder's verbal authorization — still unconfirmed by Claude Code as of the last engineering report. Not blocking commercial work; verify next time engineering is touched.

# Clinical Safety Officer (CSO) — Role & Appointment Brief (TEMPLATE)

**Status:** DRAFT TEMPLATE — ready for a buyer/adopting organization to complete and adopt.
Not a legal appointment instrument on its own; your organization's HR/QMS process should
formalize it.

**Purpose:** This brief exists because [QMS-002_CSO_Ratification_Protocol.md](QMS-002_CSO_Ratification_Protocol.md)
and [QMS-001_DHF_Structure.md](QMS-001_DHF_Structure.md) both identified the same blocker:
neither document can be executed to completion without a named individual holding this role.
This brief is what you hand to a candidate (or your existing Medical Director) to determine
fit and formalize the appointment.

---

## 1. Why this role exists for this product

The ICU Edge Gateway's waveform DSP pipeline carries two characterized, currently
**unratified** residual risks — HAZARD-DSP-005 and HAZARD-DSP-006 — packaged for decision in
QMS-002. Beyond this initial ratification, ongoing use of the product requires someone with
standing authority to:

- Accept, reject, or conditionally accept residual risk under ISO 14971 §7.
- Re-evaluate risk acceptance when a documented trigger fires (e.g., HAZARD-DSP-005's
  trigger: "any future feature derives scoring or clinical display directly from waveform
  data").
- Serve as the clinical authority referenced throughout the codebase's own hazard
  documentation (e.g., `news2_calculator.py`'s HAZARD-NEWS2-001 through 003 tags all assume
  a clinical owner exists to adjudicate scoring-boundary questions).

## 2. Required Credentials (minimum bar — adjust to your organization's policy)

| Requirement | Rationale |
|---|---|
| Active clinical license (physician, or equivalent) with critical care / acute care / ICU experience | The product's clinical domain (NEWS2 early warning scoring, ICU bedside monitoring) requires domain-competent judgment, not general IT/QA sign-off |
| Working familiarity with the NEWS2 (RCP 2017) scoring algorithm | The product's core clinical logic; a CSO unfamiliar with NEWS2's design intent cannot meaningfully evaluate HAZARD-NEWS2-* or DSP-005/006's clinical exposure claims |
| Familiarity with, or willingness to be briefed on, ISO 14971 risk management concepts | QMS-002's evaluation framework assumes basic fluency with severity/probability/detectability scoring |
| Organizational authority to bind the manufacturer on risk-acceptance decisions | Must be a documented delegation from your Quality Manual — a clinically qualified individual without this authority cannot complete QMS-002 §5 in a way that has QMS standing |
| **Not required, but useful:** biomedical/clinical engineering background | Helps independently evaluate the DSP-005/006 technical claims (filter stage ordering, group-delay-based margins) rather than relying solely on the packaged summary |

**If your organization prefers a two-role split** (e.g., a Medical Director for clinical
judgment + a separate Biomedical/Clinical Safety Engineer for technical risk evaluation),
this brief and QMS-002 both accommodate that — just ensure both roles' sign-offs appear on
the QMS-002 §5 record, or that one role's authority explicitly covers the other's scope.

## 3. Scope of Authority

- Execute [QMS-002 §5](QMS-002_CSO_Ratification_Protocol.md#section-5--formal-sign-off-template)
  sign-off records for HAZARD-DSP-005 and HAZARD-DSP-006.
- Confirm, override, or replace the S/P/D scoring template proposed in QMS-002 §2 with your
  organization's adopted risk matrix, if different.
- Own the re-review schedule and escalation-trigger monitoring described in QMS-002 §5/§6.
- Serve as the named clinical authority in future ISO 14971 risk evaluations as the product
  evolves (new hazards will be identified over time — this is not a one-time appointment).
- **Not in scope for this role alone:** REG-001's regulatory classification decision, which
  requires Regulatory Affairs / legal counsel in addition to clinical judgment (see
  [REG-001 draft §B.4](REG-001_Intended_Use_and_CDS_Exemption_Draft.md#b4-conclusion-draft-pending-your-regulatoryLegal-review)).
  The CSO should be consulted on REG-001 but is not positioned to resolve it alone.

## 4. First 30 Days — Onboarding Checklist for the Appointed CSO

- [ ] Read [REG-001_Intended_Use_and_CDS_Exemption_Draft.md](REG-001_Intended_Use_and_CDS_Exemption_Draft.md)
      in full — understand the Function A/B distinction and why the product's regulatory
      classification is currently undecided.
- [ ] Read [QMS-001_DHF_Structure.md](QMS-001_DHF_Structure.md) — understand what design-
      control and risk-management records exist, and what's still a gap (most of it, per
      that document's own honest accounting).
- [ ] Read [QMS-002_CSO_Ratification_Protocol.md](QMS-002_CSO_Ratification_Protocol.md)
      Sections 3 and 4 in full, including the underlying test files it cites
      (`test_hl7v2_waveform_pipeline.py`, `test_artifact_rejector.py`) if independent
      technical verification is desired.
- [ ] Execute QMS-002 §5 sign-off for HAZARD-DSP-005.
- [ ] Execute QMS-002 §5 sign-off for HAZARD-DSP-006.
- [ ] Confirm or adjust the S/P/D risk matrix template in QMS-002 §2 against your
      organization's adopted policy, if one exists.
- [ ] Update QMS-001 §4.2's risk traceability table to reflect the executed decisions.
- [ ] Weigh in on REG-001 from a clinical-use perspective, coordinating with Regulatory
      Affairs/legal counsel on the final classification decision.
- [ ] Confirm awareness of the one open, not-yet-actioned hazard outside this brief's scope:
      HAZARD-PROTO-002 (waveform sampling-rate defaults need per-monitor-model validation
      before clinical use against any specific monitor model) — this is an engineering/
      biomedical-engineering task, but the CSO should know it exists.

## 5. Appointment Record (fill in and retain per your document-control procedure)

```
═══════════════════════════════════════════════════════════════════════════
CLINICAL SAFETY OFFICER APPOINTMENT RECORD
═══════════════════════════════════════════════════════════════════════════

Organization:                  _________________________________________
Product covered:                ICU Edge-to-FHIR Interoperability Gateway v1.0.0

Appointee Name:                 _________________________________________
Credentials / License #:        _________________________________________
Role Title:                     _________________________________________
                                 [ Clinical Safety Officer / Medical Director /
                                   Split-role — specify: __________________ ]

Effective Date:                 _________________________________________
Delegated Authority Reference:  _________________________________________
                                 (cite the Quality Manual provision)

Onboarding checklist (§4) completed:   [ Yes / In progress, target date: ____ ]

Approved by (Quality/Regulatory lead):
Name:                           _________________________________________
Signature:                      _________________________________________
Date:                           _________________________________________

═══════════════════════════════════════════════════════════════════════════
```

---

*This brief was drafted from the codebase's existing hazard documentation and this project's
QMS-001/QMS-002 drafts. It does not itself grant any authority — it is a template for your
organization's own appointment process.*

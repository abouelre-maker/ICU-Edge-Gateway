# Buyer Due-Diligence Access — GitHub Architecture

**Owner:** Eng. Housam Ashraf — Biomedical Engineer & HealthTech Solutions Architect
**Repository:** `abouelre-maker/ICU-Edge-Gateway` (private)
**Purpose:** let a buyer's CTO or architect verify the asset without publishing the IP.

---

## 1. The governing principle

You are selling an evidence trail as much as a codebase. That creates a tension: the evidence is only
persuasive if the buyer can inspect it, but the code loses its value the moment it is public. The
resolution is **staged disclosure** — each stage reveals more, and each stage is gated on the buyer
giving you something in return (time, an NDA, a term sheet).

Never send a zip. A zip is an uncontrolled, un-revocable copy with no audit trail. Every stage below
keeps access revocable.

---

## 2. The four disclosure stages

| Stage | Buyer has given you | They get | Mechanism |
|---|---|---|---|
| 0 — Cold | Nothing | One-pager, Loom, architecture diagrams | Email attachment / link |
| 1 — Interested | A call | Read-only docs + test evidence, no `src/` | Second repo (see §3) |
| 2 — Evaluating | Mutual NDA signed | Read-only access to the full private repo | GitHub collaborator, `Read` role |
| 3 — Diligence | Signed LOI or term sheet | Full repo + live environment + your time | As stage 2, plus scheduled sessions |

**Do not skip stage 1.** It is the cheapest way to separate serious buyers from tire-kickers, and it
costs you nothing to grant.

---

## 3. Stage 1 — the evidence repo

Create a **second, separate private repository** — `ICU-Edge-Gateway-Evidence`. It contains no `src/`.
It contains:

- `README.md` — architecture overview, the Mermaid diagrams, the verified claims sheet
- `docs/` — API specification, OpenAPI JSON, the Software Architecture Description
- `evidence/` — CI run logs, the coverage report (HTML export), the test-name manifest
- `tests/` — **optional and powerful.** Test *names* and docstrings prove rigour without shipping the
  implementation. `pytest --collect-only -q > evidence/test_manifest.txt` gives you 816 lines that
  read as a specification. This is often the single most persuasive artifact you have.

A CTO who reads `test_manifest.txt` and sees `test_news2_respiratory_rate_boundary_at_exactly_21`
understands your engineering discipline in about ninety seconds. That is a better first impression
than the source itself would make.

---

## 4. Stage 2 — granting access to the real repo

GitHub's `Read` role on a private repo is exactly the right permission. It allows clone, browse,
history, and Actions logs; it does not allow push, force-push, deletion, or settings changes.

**To grant:** repo → Settings → Collaborators and teams → Add people → their GitHub username → role
`Read`.

**Practical rules:**

- **Named individuals only.** Never add a shared or role account. You want the audit log to name a
  person.
- **Use an Outside Collaborator, not an org member,** so their access is scoped to this one repo.
- **Set a calendar reminder to revoke** — 30 days is a reasonable default. Access that outlives the
  evaluation is access you have forgotten about.
- **Audit periodically:** Settings → Collaborators shows the current list. Insight → Dependency graph
  is not what you want; the useful log is your organization's audit log if the repo sits in an org.

**Do not use** a public fork, a temporary public window, or a "we'll make it public for an hour"
arrangement. GitHub is crawled continuously; a repo that is public for an hour is public forever.

**Deploy keys and PATs:** not appropriate here. A deploy key is for machines; a fine-grained PAT you
generate and hand over is a credential you cannot easily attribute or revoke per-person. Collaborator
access is the correct primitive.

---

## 5. What the NDA needs to cover before stage 2

This is a list to hand your counsel, not legal advice, and you should have a lawyer draft or review
the actual document:

- Mutual, so the buyer will actually sign it — one-way NDAs from an unknown counterparty get stalled
  in their legal queue for weeks
- Definition of confidential information that explicitly includes source code, test artifacts, and
  architecture documentation
- No-reverse-engineering and no-derivative-works clauses
- A residuals clause you have actually read — buyer-side counsel often inserts one that would let
  them rebuild your design from memory
- Survival period: 3–5 years is standard for technical IP
- Return-or-destroy on termination
- Explicit statement that the NDA grants no licence and no right to use

---

## 6. Protecting yourself before anyone looks

Do these before stage 2, not after:

1. **Establish provenance.** Your git history is your best evidence of authorship — 53 commits with
   dated, individually-evidenced messages, preserved through a true merge rather than a squash. That
   history is an asset; do not rewrite it.
2. **Add a LICENSE and copyright header decision.** An unlicensed private repo is "all rights
   reserved" by default, which is what you want — but be deliberate about it and be able to say so.
3. **Confirm your third-party dependency licences are clean.** A buyer's counsel will run this scan.
   Run `pip-licenses` yourself first so you are not surprised by a copyleft dependency in your own
   diligence meeting.
4. **Confirm you own it outright.** No employer IP-assignment agreement, no university claim, no
   contractor contributions without assignment. If there is any ambiguity here, resolve it with
   counsel before you take a meeting — it is the single most common reason technical-asset deals die.

Item 4 is the one founders skip and the one that kills deals. Handle it first.

---

## 7. What to say when they ask for the code on the first call

> "Happy to — the repo is private and I grant read access under a mutual NDA. Before that, I can send
> you the architecture docs and the full test manifest, which is usually enough to tell you whether
> this is worth your legal team's time. Want me to send that today?"

This is a normal, professional answer. A buyer who objects to signing a mutual NDA before receiving
source code is telling you something useful about how the rest of the deal would go.

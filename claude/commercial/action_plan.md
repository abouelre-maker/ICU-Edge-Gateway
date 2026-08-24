# Action Plan — Execute in This Order

**Owner:** Eng. Housam Ashraf
**Date:** 2026-08-23

The ordering is deliberate. Steps 1–3 are blockers on everything commercial; do not start outreach
before they are done. Estimated total for steps 1–4: one working day plus DNS propagation.

---

## Step 1 — Clear the demo gate (30 minutes)

The reason your last run showed **Gateway: UNREACHABLE** is that the standalone Streamlit command I
gave you launches *only* the dashboard. It never starts the FastAPI backend on port 8000, so the
dashboard came up correctly and then found nothing to talk to. That was my error — I handed you an
isolation-testing command and it read like a launch command. Discard it.

`run_demo.bat` already sequences all three processes correctly: gateway → blocking health gate →
dashboard → streamer → browser. It is the only launch path.

```
stop_demo.bat
run_demo.bat
```

`stop_demo.bat` is new — it frees ports 8000, 8501, and 2575, which will otherwise still be held by
your previous partial run and will abort `run_demo.bat` at the port pre-flight check.

If a port is held by something you cannot identify, the pre-flight now prints the owning PID and the
exact `taskkill` command. To reclaim automatically:

```
set RECLAIM_PORTS=1 && run_demo.bat
```

**Success looks like:** three console windows, the browser opening on `http://127.0.0.1:8501`, the
sidebar showing gateway **HEALTHY** rather than UNREACHABLE, and three bed cards rendering with NEWS2
scores that change every two seconds.

**Report back what you see.** The Windows Live Demo Gate does not clear until you confirm this, and
nothing goes to a buyer before it does.

---

## Step 2 — Buy the domain and set up email (45 minutes + DNS propagation)

Your current addresses — a university student address and a personal Gmail — both cost you
credibility with an enterprise buyer. This is the highest return-per-dollar action available to you.

**Choosing the domain.** `icu-edge.io` is a reasonable candidate but check availability yourself
before committing; I have not verified it and domain availability changes hourly. Alternatives in the
same register: `icuedge.io`, `icu-edge.dev`, `edgegateway.health`. Prefer `.io` or `.dev` over `.health`
on cost. Avoid a hyphen if a clean equivalent is free — hyphens get lost when spoken on a call.

**Registrar.** Cloudflare Registrar sells at wholesale with no markup and includes WHOIS privacy at no
extra charge. Namecheap and Porkbun are equivalent alternatives. Expect roughly $10–$50/year depending
on TLD — `.io` typically runs higher than `.com`.

**Mailbox.** Three viable routes:

| Option | Cost | Notes |
|---|---|---|
| Google Workspace | ~$7/user/month | Familiar interface, best deliverability reputation, integrates with the Gmail you already use |
| Microsoft 365 Business Basic | ~$6/user/month | Choose this if your buyers are Microsoft-heavy and you want Teams |
| Zoho Mail | ~$1/user/month | Cheapest credible option; deliverability is adequate but not Google-tier |

For cold outreach where deliverability decides whether you get read at all, Google Workspace is worth
the difference over Zoho.

**Steps:**

1. Check availability and register the domain.
2. Create the mailbox — `housam@yourdomain` reads better than `hello@` or `info@` for a solo founder.
   A personal name signals a person; a role address signals a company that does not exist yet.
3. **Configure SPF, DKIM, and DMARC.** Your provider gives you the DNS records; add them at the
   registrar. This is not optional — cold email from a fresh domain without proper authentication
   lands in spam, and you will conclude your pitch failed when in fact it was never delivered.
4. **Warm the domain for 7–14 days before any cold campaign.** Send and receive normal, low-volume
   mail first. A brand-new domain that immediately sends 25 cold emails gets flagged. Start your first
   batch small — five — as the outreach kit already prescribes.
5. Update your LinkedIn contact details to the new address.

**Deliverability is why the warming step exists.** Skipping it is the most common way a technically
sound outreach campaign produces zero replies for reasons that have nothing to do with the pitch.

---

## Step 3 — Confirm you own the IP outright (do this before any buyer conversation)

This is the single most common reason technical-asset deals collapse in diligence, and it is entirely
resolvable in advance:

- No current or former employer with an IP-assignment clause covering work in this domain.
- No university claim arising from your studies, supervision, or use of institutional resources.
- No contractor or collaborator contributions without a written assignment.
- Third-party dependency licences clean — run `pip-licenses` yourself before a buyer's counsel does.

If there is any ambiguity, resolve it with counsel now. A buyer discovering it in week six of
diligence does not renegotiate; they walk.

---

## Step 4 — Apply the accessibility fix (10 minutes)

Two risk-band colours currently sit at WCAG AA-large rather than AA. In `demo/dashboard_logic.py`,
`RISK_STYLES`:

- `LOW` background `#558b2f` → `#456f26` (contrast 4.10 → 5.91)
- `MEDIUM` background `#ef6c00` → `#bf360c` (contrast 3.08 → 5.60)

Demo layer only — outside `src/`, no validated clinical algorithm touched, no test modified. Do it
before recording the Loom so the recorded artifact is the compliant one. Detail in
`architecture_and_ux_spec.md` §4.4.

---

## Step 5 — Record the Loom (30 minutes including retakes)

Only after step 1 confirms and step 4 is applied. Script is in `module1_outreach_kit_2026-08-23.md`,
word for word, timestamped.

Run `stop_demo.bat` then `run_demo.bat` immediately before recording so the bed wall starts from a
clean state and the NEWS2 progression reads clearly from the beginning.

---

## Step 6 — Build the send list (2–3 hours)

From `buyer_database_north_america.md`. Start with Tier 1 (interoperability vendors) — fastest
technical evaluation and the feedback sharpens your pitch before you spend your one shot at the
monitoring OEMs.

For each company you must be able to write one specific sentence about why *them*. If you cannot, drop
it. Target 20–25 companies, not 250.

Source the individual from LinkedIn Sales Navigator at send time using the titles listed per tier —
never use a name from a static list, because it will be stale.

---

## Step 7 — Set up the stage-1 evidence repo (1 hour)

Per `github_due_diligence_access.md` §3. Create `ICU-Edge-Gateway-Evidence` as a second private repo
containing docs, CI evidence, and the test manifest — no `src/`.

Generate the manifest now, because it is your most persuasive single artifact:

```
venv311\Scripts\python.exe -m pytest --collect-only -q > evidence\test_manifest.txt
```

816 lines that read as a specification. A CTO who sees
`test_news2_respiratory_rate_boundary_at_exactly_21` understands your engineering discipline faster
than the source code would convey it.

---

## Step 8 — Send batch one (1 hour)

Five emails. Template and four-touch cadence in the outreach kit. Track reply rate per subject line;
adjust after the first fifteen.

---

## Running in parallel — start now, do not wait for a reply

- **US entity formation.** The bank account is the long pole for a non-resident founder, measured in
  weeks. You do not want a warm counterparty waiting on it. Structure guidance is in the pricing
  framework §7.1.
- **Identify counsel.** M&A/IP attorney and a cross-border tax advisor. You do not need to retain them
  today; you need to know who you would call when a term sheet arrives.

---

## Still open, tracked, not forgotten

| Item | Status |
|---|---|
| WINDOWS-LIVE-DEMO-GATE | Fix applied, awaiting your confirmation (step 1) |
| GAP-DOCKER-SIZE-001 | 372 MB vs 150 MB target — disclosed, not fixed |
| REG-CITATION-001 | One emitted site fixed; ~20 label-only sites await counsel |
| HAZARD-DSP-007 | Drafted proposal, awaiting qualified human sign-off |
| FLAKE-MQTT-001 | Recorded, not root-caused |
| `pytest-cov` in `requirements.txt` | Authorized for removal, execution unconfirmed |
| 27 files showing modified in git | Needs native check by Claude Code — likely bridge artifact, do not act on my reading |

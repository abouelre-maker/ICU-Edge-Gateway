# Hardening Run State (Track E)
branch: hardening/v2-on-public-main
base: origin/main @ fdc5370 (public research release, 2026-11-16)
ported_from: hardening/assessment-2026-09 @ 7b6d472 (21 engineering commits, same messages)
interpreter: Python 3.11.9
last_phase_completed: 2
current_phase: 3 (security findings outside Phase 2: F-05, F-06/07, F-12, F-13, S-01..S-06 worked)
baseline: 816 passed, 1 xfailed, 95% coverage
current: 1045 passed, 4 xfailed, 0 failed, 95% coverage (3130 statements)
ruff: clean (exit 0)
mypy: clean (54 source files)
bandit: clean
pip-audit (requirements.txt): no known vulnerabilities
blocked_test_conflicts: [A2-1, A5-1, A5-2]  # HD-E6 (clinical; not part of the 2026-11-19 approval)
blocked_on_human: [HD-E1, HD-E2, HD-E3, HD-E4, HD-E5, HD-E7, HD-E8, HD-E9]
next_action: Housam reviews the PR. Open decisions: HD-E7 staleness values (the demo cannot start without them), HD-E9 FHIR output findings H-01..H-06.
updated: 2026-11-19

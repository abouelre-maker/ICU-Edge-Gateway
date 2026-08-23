# SYSTEM DIRECTIVE: ICU EDGE GATEWAY (SaMD DEVELOPMENT)

## 1. DEVELOPER PROFILE & DOMAIN
- Role: Software Engineer & SaMD Developer
- Domain: ICU Edge Systems, HL7 to FHIR Interoperability, Biomedical Signal Processing (ISO 14971)

## 2. STRICT CODE & ARCHITECTURE RULES
- Always enforce Clean Architecture and strict typing in Python.
- Never modify core clinical logic without verifying ISO 14971 risk impact.
- Prioritize running unit tests (`pytest`) after any code changes.
- Ensure zero regression across the existing suite: **816 passed, 1 xfailed**
  (verified 2026-08-21 on venv311 / Python 3.11.9, which matches the CI pin).
  Treat this number as the regression contract and update it here whenever
  tests are legitimately added, so it does not drift stale again.

## 3. PHASE 6 COMMANDS
- Test execution: `pytest --cov=src`
- Linting: `ruff check src tests`
# SYSTEM DIRECTIVE: ICU EDGE GATEWAY (SaMD DEVELOPMENT)

## 1. DEVELOPER PROFILE & DOMAIN
- Role: Software Engineer & SaMD Developer
- Domain: ICU Edge Systems, HL7 to FHIR Interoperability, Biomedical Signal Processing (ISO 14971)

## 2. STRICT CODE & ARCHITECTURE RULES
- Always enforce Clean Architecture and strict typing in Python.
- Never modify core clinical logic without verifying ISO 14971 risk impact.
- Prioritize running unit tests (`pytest`) after any code changes.
- Ensure zero regression across all existing 311 unit tests.

## 3. PHASE 6 COMMANDS
- Test execution: `pytest --cov=src`
- Linting: `ruff check src tests`
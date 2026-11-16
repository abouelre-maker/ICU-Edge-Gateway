# Contributing

Thank you for your interest in this project. Bug reports, replication attempts, critical
reviews of the methods or the risk analysis, and code contributions are all welcome.

## Ground rules

- **Research use only.** Contributions must not add features intended for live clinical
  use, and must not add real patient data. Test data must be synthetic.
- **Clinical algorithms are change-controlled.** Changes to the NEWS2 calculator
  (`src/domain/services/news2_calculator.py`), the physiological bounds, or the DSP
  filters (`src/domain/services/artifact_rejector.py`) must cite the clinical or
  engineering source for the change, update the affected tests in `tests/regulatory/`,
  and update the risk file (`docs/RMF-001_Risk_Management_File.md`) and traceability
  matrix (`docs/RTM-001_Requirements_Traceability_Matrix.md`) where relevant.
- **No silent behavior changes.** Every behavior change needs a test that fails before the
  change and passes after it.

## Development setup

Python 3.11 is used in CI.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
```

## Checks to run before opening a pull request

These are the same checks the CI quality gate runs:

```bash
ruff check src/ tests/
mypy src/
bandit --recursive src/ --severity-level low --quiet
pip-audit --requirement requirements.txt --progress-spinner off
PYTHONPATH=. pytest --cov=src --cov-fail-under=90
```

## Reporting issues

Please open a GitHub issue with:

- what you expected and what happened,
- the smallest input (for example, a synthetic HL7 message) that reproduces it,
- your Python version and operating system.

For a suspected patient-safety-relevant defect in a scoring rule or filter, please say so
in the issue title so it can be prioritized. For security vulnerabilities, follow
[SECURITY.md](SECURITY.md) instead of opening a public issue.

## License of contributions

By contributing, you agree that your contributions are licensed under the
[Apache License, Version 2.0](LICENSE).

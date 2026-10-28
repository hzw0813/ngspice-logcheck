# Contributing

Use Python 3.10 or newer. Run `PYTHONPATH=src python -m unittest discover -s tests -v`; use PowerShell's `$env:PYTHONPATH = "src"` on Windows. Live tests require a separately installed ngspice and explicitly skip when unavailable.

For parser changes, include a small synthetic regression and the official output format or an original simulator-generated example. Keep runtime dependency-free, execution-free and offline. New numeric or diagnostic heuristics must state their limits. Never claim circuit correctness or silently choose one value from repeated measurements.

Do not contribute private PDKs, proprietary model files, third-party confidential logs or institution-owned material without authorization. Reports and fixtures should use small original passive circuits. Explain a concrete problem, expected behavior, and verification in each PR. Contributions use the MIT license.

# Development guidance

- Read README.md and SECURITY.md before changing parser or comparison semantics.
- The checker is offline and execution-free. Simulator use stays explicit in examples and integration tests.
- Fail on missing/duplicate/nonfinite/ambiguous requested values. Keep diagnostic limits explicit.
- Run `python -m unittest discover -s tests -v` after installing the package. Live integration tests require `NGSPICE` or ngspice on PATH; report skips accurately.
- Generated examples under examples/recorded come from scripts/generate-demo.py and original passive circuits. Never hand-edit measurements or passing results.
- Do not commit private data, PDKs, models, pilot identities or commercial planning files.

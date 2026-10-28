# ngspice-logcheck

Check required scalar values in an existing ngspice log, then compare two reports for design review. Runtime uses only Python's standard library. No simulator or netlist execution, account, network connection, or telemetry is required by the checker.

ngspice's [manual §14.5](https://ngspice.sourceforge.io/docs/ngspice-47-manual.pdf) explains that some errors can still end with exit code 0. Our original RC example reproduces an unreachable measurement that returns 0 in ngspice 47. This tool checks the supplied log values and recognized diagnostics in addition to the simulator's own exit status.

**Early prototype:** real user adoption and willingness to pay have not been established. This is a small component for existing simulation workflows, with explicit limitations below.

## Install and check a log

Python 3.10 or newer. From a source checkout, install into your preferred virtual environment:

```sh
python -m pip install .
ngspice-logcheck simulation.log --spec examples/limits.json
```

The package has no runtime dependencies; installation uses setuptools as its build dependency. It is not yet published to PyPI. For a dependency-free source-tree trial:

```sh
PYTHONPATH=src python -m ngspice_logcheck simulation.log --spec examples/limits.json
```

On PowerShell, set `$env:PYTHONPATH = "src"` before running the `python` command instead of using the POSIX environment prefix.

Try the recorded original RC example without installing a simulator:

```sh
ngspice-logcheck examples/recorded/baseline.log --spec examples/limits.json
ngspice-logcheck compare examples/recorded/baseline.json examples/recorded/candidate.json --html-out review.html
```

The first command passes; the second exits 1 and creates a report showing one newly failed measurement check. [Recorded provenance](examples/recorded/provenance.json) identifies the original circuits and simulator version. Recreate fresh artifacts with `python scripts/generate-demo.py --ngspice /path/to/ngspice --output new-demo-directory`; this separate generator explicitly runs the included circuits. Recorded data is demonstration evidence, not a fresh simulation of your design.

The JSON spec names every required measurement and its inclusive numeric bounds:

```json
{
  "schemaVersion": 1,
  "measurements": {
    "vout_final": {"min": 0.99, "max": 1.01},
    "rise_time": {"min": 0.0000021, "max": 0.0000023}
  }
}
```

Names are matched case-insensitively and must contain ASCII letters, digits or underscores, starting with a letter or underscore. Bounds are decimal JSON numbers in the same units as the log. `min` and `max` are inclusive; either may be omitted. Units are not inferred or converted. Expressions, strings, NaN/Infinity, duplicate keys, case-colliding names, and reversed bounds are rejected.

```sh
ngspice-logcheck simulation.log --spec examples/limits.json \
  --json-out run.json --junit-out junit.xml
```

Use `--format json` for machine-readable stdout. Report paths must be fresh, distinct from the inputs, and have existing parent directories. Outputs are never overwritten. If a later artifact write fails, an earlier artifact may remain; the command's exit status is authoritative.

| Exit | Meaning |
| --- | --- |
| 0 | All required supplied values meet bounds, without a recognized error. |
| 1 | A value is missing, invalid, duplicated, out of bounds, failed, or a recognized log error occurred. |
| 2 | Invalid configuration, input, arguments, or report I/O. |

The input log is limited to 16 MiB, spec to 1 MiB, comparison report inputs to 4 MiB per file, and required measurements to 1,000. Inputs must be UTF-8 regular files. Reports omit raw log excerpts and paths, retaining only names, values, limits, line numbers, fixed diagnostic codes, and SHA-256 fingerprints.

## Run the original RC example

This optional step needs a separately installed ngspice. The checker itself never starts it. Use only a netlist you trust; simulator control sections and initialization files can execute commands. The included examples are original, small passive circuits without a PDK.

```sh
ngspice -n -b examples/rc.cir > rc.log 2>&1
ngspice-logcheck rc.log --spec examples/limits.json --json-out baseline.json
```

Capture stdout and stderr together; preserve the simulator exit status as an additional check in your automation. Do not use `-r` in this example: ngspice batch rawfile output can suppress `.measure` results.

The failing example asks a 1 V RC output to cross 2 V:

```sh
ngspice -n -b examples/failed-measure.cir > failed.log 2>&1
ngspice-logcheck failed.log --spec examples/limits.json --json-out failed.json
```

ngspice 47 returned 0 for this example during our local test; the checker returned 1 for the failed `rise_time`. This is an observed version-specific case, not a promise about every simulator release.

## Compare a baseline and candidate

Check a second run into `candidate.json`, using the same measurement names and limits:

```sh
ngspice-logcheck candidate.log --spec examples/limits.json --json-out candidate.json
ngspice-logcheck compare baseline.json candidate.json \
  --json-out comparison.json --html-out review.html
```

The comparison recomputes the bounds result instead of trusting a report's `passed` flag, preserves recorded failures, and rejects mismatched limits. It shows values, signed absolute deltas, descriptive relative deltas, and new measurement-check failures. A candidate error diagnostic fails the overall comparison even when individual numbers meet bounds. The HTML is self-contained, escaped, printable, and has no external scripts or assets.

This helps prepare a review of **supplied results**. Input fingerprints identify bytes, not authenticity, recency, simulator success, PVT coverage, model quality, or circuit correctness. Report inputs are user-controlled; rechecking a JSON report does not authenticate its contents.

## Supported scope and limitations

- One finite decimal or scientific-notation scalar per requested name. Duplicate values fail even if equal; use separate logs for sweeps, corners, appended output, and repeated analyses.
- Numeric metadata tails `at/from/to/trig/targ/with` are accepted. Scale suffixes such as `1m`, arbitrary trailing text, non-finite values and nonzero values that underflow binary64 to zero are rejected. Ordinary binary64 rounding still applies; this is not exact-decimal metrology.
- Missing results and recognized measure failures fail. Known `Error`, decorated errors, fatal messages, final abort/interruption, and timestep failures fail globally. Recoverable warnings are visible and do not fail. Diagnostic recognition is deliberately incomplete.
- Arbitrary unrelated lines are ignored. A simulator banner or completion marker is not required; an echoed assignment can look like a measurement. A truncated log containing all required results could pass. The checker does not attest run completion or freshness.
- LTspice, Spectre, HSPICE, Xyce, waveform/raw parsing, signed artifacts, simulator orchestration, and signoff are outside this prototype's supported contract.
- Reports can reveal names, values and specifications even without raw logs. Review them before sharing. See [SECURITY.md](SECURITY.md).

## Alternatives

[CACE](https://github.com/fossi-foundation/cace) offers full analog characterization and a web interface; [spicelib](https://github.com/nunobrum/spicelib) offers multi-simulator Python automation and data analysis. Commercial [Cadence ADE](https://www.cadence.com/en_US/home/tools/custom-ic-analog-rf-design/circuit-design.html) provides extensive simulation and verification management. They may already meet your needs. This prototype tests a narrower workflow: import existing logs without restructuring the circuit project or adopting simulator orchestration.

## Development and feedback

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
```

Live integration tests run when `ngspice` is on PATH or `NGSPICE` points to an executable. They are explicitly skipped otherwise. CI includes a dedicated Linux job with ngspice, plus parser/CLI tests across operating systems and Python versions. See [CONTRIBUTING.md](CONTRIBUTING.md) and [pilot guide](docs/pilot.md).

MIT licensed. Maintainer: [@hzw0813](https://github.com/hzw0813). No independent users, customers, patents, funding, or OpenAI program approval are claimed.

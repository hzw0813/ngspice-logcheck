# ngspice-logcheck

Offline scalar result checks and comparison reports. `ngspice-logcheck` reads ngspice logs; the `simreview` preview compares explicitly normalized CSV tables with test, corner, point and unit identity. Runtime uses only Python's standard library. Neither checker executes a simulator or netlist, requires an account, connects to a network, or sends telemetry.

ngspice's [manual §14.5](https://ngspice.sourceforge.io/docs/ngspice-47-manual.pdf) explains that some errors can still end with exit code 0. Our original RC example reproduces an unreachable measurement that returns 0 in ngspice 47. This tool checks the supplied log values and recognized diagnostics in addition to the simulator's own exit status.

**Early prototype:** real user adoption and willingness to pay have not been established. This is a small component for existing simulation workflows, with explicit limitations below.

## Five-minute trial from a clean checkout

Requires Git and Python 3.10 or newer. Obtain the source bundle so the documented examples are available:

```sh
git clone --branch v0.2.0 https://github.com/hzw0813/ngspice-logcheck.git
cd ngspice-logcheck
python -m venv .venv
```

Activate the environment with `source .venv/bin/activate` on macOS/Linux, or `.venv\Scripts\Activate.ps1` on PowerShell. Then install:

```sh
python -m pip install .
simreview examples/tables/baseline.csv examples/tables/candidate.csv --spec examples/tables/limits.json --html-out table-review.html
```

The synthetic candidate deliberately has two failed checks. **Exit 1 is expected** and `table-review.html` is created. Open it in a browser. These tables are hand-authored contract examples, not native ADE exports or results from a licensed simulator.

Prefer the actual original ngspice recording? No simulator is needed to read it:

```sh
ngspice-logcheck examples/recorded/baseline.log --spec examples/limits.json
ngspice-logcheck compare examples/recorded/baseline.json examples/recorded/candidate.json --html-out review.html
```

The baseline command exits 0; the comparison exits 1 and creates one newly failed measurement check. [Recorded provenance](examples/recorded/provenance.json) identifies the original circuits and simulator version. These are demonstration inputs, not a fresh simulation of your design.

Package installation uses setuptools as a build dependency; runtime has no dependencies. The package is not published to PyPI. A [release wheel](https://github.com/hzw0813/ngspice-logcheck/releases/tag/v0.2.0) can be installed with `python -m pip install /path/to/downloaded.whl`, but **examples and documentation require the source bundle or checkout**, not a wheel-only installation.

## Review normalized CSV results

`simreview` accepts this explicit, case-sensitive table contract:

```csv
test,corner,point,measurement,value,unit,status
ota_ac,tt_27C,nominal,gain,65,dB,ok
ota_ac,ss_85C,nominal,gain,,dB,failed
```

Every expected identity and its unit/bounds appears separately in a JSON spec:

```json
{
  "schemaVersion": 1,
  "measurements": [
    {"test":"ota_ac","corner":"tt_27C","point":"nominal","measurement":"gain","unit":"dB","min":60},
    {"test":"ota_ac","corner":"ss_85C","point":"nominal","measurement":"gain","unit":"dB","min":60}
  ]
}
```

Run one comparison with a shared spec:

```sh
simreview baseline.csv candidate.csv --spec limits.json --json-out comparison.json --html-out table-review.html
```

**Native Cadence/ADE CSV is not directly supported.** Map your export explicitly to this contract; retain the original file and do not invent missing context. The [Cadence export guide](docs/cadence-export.md) cites public export methods and their version-dependent limits. Actual ADE export compatibility still needs a permissioned, sanitized sample.

The identity is `(test, corner, point, measurement)`. `point` must explicitly identify a sweep/iteration or the user-declared `nominal` case. Same-name results from different tests, corners or points are distinct. Units are required, exact and never converted. Missing/duplicate observations, mismatched units, failed exporter status and invalid numbers fail checks; unsupported extra identities require explicit normalization and are rejected. Details and limits: [table format](docs/table-format.md).

## Check your own ngspice log

From the source directory after installation:

```sh
ngspice-logcheck simulation.log --spec examples/limits.json
```

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

The input log is limited to 16 MiB, spec to 1 MiB, comparison report inputs to 4 MiB per file, and required measurements to 1,000. `simreview` permits up to 16 MiB / 10,000 rows in each CSV and 1,000 expected identities. Inputs must be UTF-8 regular files. Reports retain requested identities, units, values, limits, row/line numbers and SHA-256 fingerprints; they omit raw log excerpts and local paths.

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

ngspice 47 returned 0 for this example during our local test; the checker returned 1 for the failed `rise_time`. This is an observed version-specific case, not a promise about every simulator release. Recreate the original recorded set with `python scripts/generate-demo.py --ngspice /path/to/ngspice --output new-demo-directory`; this separate generator explicitly runs the included circuits.

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
- Native LTspice, Spectre/ADE, HSPICE and Xyce file formats, waveform/raw parsing, signed artifacts, simulator orchestration, and signoff are outside this prototype's supported contract. Manually normalized CSV is a separate explicit data contract, not native simulator-format support.
- Reports can reveal names, values and specifications even without raw logs. Review them before sharing. See [SECURITY.md](SECURITY.md).

## Alternatives

[CACE](https://github.com/fossi-foundation/cace) offers full analog characterization and a web interface; [spicelib](https://github.com/nunobrum/spicelib) offers multi-simulator Python automation and data analysis. Commercial [Cadence ADE](https://www.cadence.com/en_US/home/tools/custom-ic-analog-rf-design/circuit-design.html) provides extensive simulation and verification management. They may already meet your needs. This prototype tests a narrower workflow: import existing logs without restructuring the circuit project or adopting simulator orchestration.

## Development and feedback

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
```

Live integration tests run when `ngspice` is on PATH or `NGSPICE` points to an executable. They are explicitly skipped otherwise. CI includes a dedicated Linux job with ngspice, plus parser/CLI tests across operating systems and Python versions. See [CONTRIBUTING.md](CONTRIBUTING.md) and [pilot guide](docs/pilot.md).

MIT licensed. Maintainer: [@hzw0813](https://github.com/hzw0813). No independent users, customers, patents, funding, or OpenAI program approval are claimed.

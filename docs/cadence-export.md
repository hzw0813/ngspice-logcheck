# Prepare an ADE scalar export for SimReview

SimReview reads the normalized CSV contract below. It does **not** directly parse arbitrary Cadence ADE exports, Spectre logs, PSF databases or waveforms. The examples are synthetic; no Cadence installation, license, PDK or real ADE export was used to validate them.

## Export an existing result

1. Record your Virtuoso version/subversion, ADE flavor (Explorer, Assembler or XL), history and export view. Open the intended existing history and confirm its scalar outputs have been evaluated.
2. Export the scalar results table as CSV. Public Cadence guidance describes the Detail/Detail-Transpose views and a CSV/HTML export control; the exported columns depend on the visible view. Verify the controls in your installed version. [Public export guidance](https://community.cadence.com/cadence_technology_forums/f/custom-ic-design/29207/exporting-monte-carlo-simulation/1333580)
3. For an existing active maestro session, Cadence's public TeamADE article shows this export call:

   ```lisp
   maeExportOutputView(?fileName "simResults.csv" ?view "Detail")
   ```

   This is an export example, not a complete session setup or simulation script. Check the function and supported arguments in your installation's SKILL API Finder (CIW → Tools → Finder). We do not execute it, start Virtuoso/Spectre or change global GUI settings. [TeamADE article](https://community.cadence.com/cadence_blogs_8/b/cic/posts/analog-design-resonance-quick-and-efficient-regression-scripts-now-possible-with-ade-explorer-and-ade-assembler)
4. Preserve the original CSV. Inspect the actual headers and rows before mapping; these public references span several releases and do not establish one universal ADE CSV layout.

## Check context before mapping

- **Test identity:** Detail-Transpose exports can omit test names, making identically named outputs ambiguous. Enable the relevant test-name display/export option using your version's documentation, or export tests separately and record their identity explicitly. Do not infer a test from an output name. Specs may require a separate export. [Cadence discussion](https://community.cadence.com/cadence_technology_forums/f/custom-ic-design/55452/ade-results-detailed---transposed-and-csv-export-missing-spec-and-testname)
- **Corners and points:** use per-point scalar results. A Yield table can contain aggregate statistics; it is not interchangeable with individual corners or Monte Carlo iterations. Expansion/export choices can affect retained corner rows. [Corner export discussion](https://community.cadence.com/cadence_technology_forums/f/custom-ic-design/40461/export-monte-carlo-yield-corner-data-in-csv/1357384), [iteration views](https://community.cadence.com/cadence_technology_forums/f/custom-ic-design/31478/how-to-retrieve-an-output-from-every-monte-carlo-iteration/1340259)
- **Units and failed values:** exported representations vary with settings. A public staff reply discusses units and `valuesAsInGUI`, while another thread reports `eval err` for failed expressions. These are clues to inspect, not an exhaustive grammar or an instruction to change your configuration. Never convert missing/failed values to zero. [Units](https://community.cadence.com/cadence_technology_forums/f/custom-ic-skill/66167/export-measurement-units-with-axlexportoutputview-ade-maestro-results-monte-carlo/1408923), [failure example](https://community.cadence.com/cadence_technology_forums/f/custom-ic-design/47027/export-ade-output-expressions-to-csv)

## Normalize explicitly

Use exactly this header, in this order:

```csv
test,corner,point,measurement,value,unit,status
amp_ac,tt,nominal,gain,60,dB,ok
amp_ac,ss,nominal,gain,,dB,failed
```

The two rows above are **synthetic contract examples**, not an ADE export.

| Field | Manual mapping rule |
| --- | --- |
| `test` | Exact test label, confirmed from the selected result context. |
| `corner` | Exact corner label. Preserve distinctions such as model, temperature and voltage settings in your mapping notes. |
| `point` | Explicit `nominal`, or a stable identifier for a sweep point/iteration. Use the same identity in both runs only when the conditions correspond. |
| `measurement` | Exact scalar output label, not a waveform or an evaluated expression supplied to SimReview. |
| `value` | Finite decimal/e-notation number for `ok`; blank for `failed`. `1m` is not accepted. |
| `unit` | Explicit unit label. No inference or conversion occurs; consistently normalize units yourself before comparison. |
| `status` | Exactly `ok` or `failed`. Preserve every expected failure/missing result as a failed row. |

Identity is the case-sensitive tuple `(test, corner, point, measurement)`. The limits JSON has `schemaVersion: 1` and a `measurements` list; each entry supplies that identity, `unit`, and `min` and/or `max`. See the [synthetic limits example](../examples/tables/limits.json).

Unknown extra identities are rejected. Missing/duplicate identities, failed rows and unit mismatches fail validation/comparison. Select the intended scope deliberately and retain all expected outcomes; do not silently discard failed rows or merge tests, corners or points to make a table pass.

## Preview the synthetic workflow

After installing the current source checkout, run from its root with fresh output paths:

```sh
simreview examples/tables/baseline.csv examples/tables/candidate.csv \
  --spec examples/tables/limits.json \
  --html-out review.html --json-out comparison.json
```

This previews the normalized-table workflow. It does not validate an installed Cadence release. Input fingerprints identify supplied bytes; they do not attest run freshness, authenticity, completed simulation, matching PDKs or signoff.

## What an actual compatibility pilot needs

Provide only data you are allowed to share: original sanitized headers and a few scalar rows from the actual export, two corners, one successful value and one failed/missing value. Two tests sharing one output name are particularly useful. Record version, view, history context, unit formatting and every normalization step. PDKs, netlists, PSF data, proprietary expressions and personal identities are unnecessary.

A blank or synthetic table is enough to discuss the workflow, but it is not evidence of native ADE export compatibility. Keep real samples and reports out of public issues unless the rights holder has approved them; see [data handling](../SECURITY.md).

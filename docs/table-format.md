# Normalized scalar CSV contract

`simreview` compares two already-produced tables under a shared, explicit JSON spec. It does not read a Cadence database, guess native CSV layouts, infer missing context or units, execute expressions, run Spectre, or evaluate circuit correctness.

## Table

The exact header field set is `test,corner,point,measurement,value,unit,status`. Header order may differ. Missing, duplicate or extra columns, inconsistent row widths and malformed CSV are invalid input. Blank records may be ignored. CSV quoting is supported; arbitrary format sniffing is not.

`test`, `corner`, `point` and `measurement` form an exact case-sensitive identity. Each is a printable label of 1–128 characters, without leading/trailing whitespace or control characters. `point` must explicitly preserve sweep/iteration identity; declare `nominal` only when that is actually your context. `unit` is a required exact printable label of 1–32 characters. `s`, `us` and `µs` are distinct; the importer never converts them. Use an explicit convention such as `1` for dimensionless values in both spec and table.

`status` is either `ok` or `failed`. An `ok` value must be a finite decimal or e/E scientific-notation number in the declared unit, without SPICE suffixes or an attached unit. An invalid/blank/nonfinite numeric value fails its observation. `failed` requires a blank value; preserve the export failure instead of turning it into 0. Any unsupported status or invalid schema needs explicit mapping first.

## Spec

Root fields are only `schemaVersion: 1` and `measurements`, a list of 1–1,000 entries. Each entry contains the exact identity labels, a unit, and at least one finite numeric `min` or `max`. Limits are inclusive and `min <= max`. Duplicate identity entries, JSON keys, nonfinite values, booleans as numbers and unknown fields are rejected.

Every CSV identity must exist in the spec. Filter/map unwanted entries explicitly; unknown contexts are invalid input rather than silently ignored. A required identity that is missing, repeated, failed, numerically invalid, or in the wrong unit fails its check. Repeated identical numbers are still ambiguous.

## Comparison and output

The same spec applies to both runs. Deltas are candidate minus baseline in the same declared unit, with no conversion. A delta is descriptive, not an assertion that a larger/smaller number is better. New failures count pass-to-fail transitions under the same bounds. Missing, ambiguous, failed or mismatched-unit observations have no comparable scalar or delta. Zero-baseline relative deltas and binary64 arithmetic bounds produce null and a fixed note.

Exit 0 means candidate checks pass, 1 means a candidate check fails, and 2 means invalid input/configuration/arguments or I/O. A failing baseline is visible separately. All interpretation is limited to supplied tables and declarations; a checked CSV may be incomplete, stale, manually edited or forged.

Each CSV is at most 16 MiB and 10,000 data rows; the spec is at most 1 MiB. UTF-8 regular files only. CSV row numbers refer to the physical line where the parsed record ends. Binary64 rounding applies; nonfinite numbers, overflow, and nonzero decimal underflow to zero are rejected when parsing text.

Output paths must be fresh, mutually distinct and different from inputs. Parent directories must already exist. No output is overwritten. An earlier artifact may remain if a later write fails; use the command's exit status. Reports expose declared labels, units, bounds and measurements, so inspect them before sharing.

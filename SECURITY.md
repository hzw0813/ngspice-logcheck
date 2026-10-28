# Security and data handling

The checkers read regular local files and write only explicitly requested fresh report paths. They do not run a simulator, evaluate expressions, execute a shell, call a network service or upload data. Specs are bounded JSON data; `simreview` accepts only an explicit normalized scalar CSV contract. Simulator execution in examples and integration tests is separate and explicit.

Logs, tables and reports may contain confidential test/corner/point labels, measurement names, units, values and limits. Reports omit raw excerpts and local input paths, but they are not anonymized. Inspect artifacts before sharing; do not upload private models or PDKs to public issues. Avoid placing private reports in a publicly served directory. CSV mapping, point identity, unit labels and exporter statuses are user declarations; they are not independently attested by the comparison.

SHA-256 identifies supplied input bytes. It does not establish authenticity, freshness, a trusted process, run completion, circuit correctness, model validity or signoff. A log or report can be forged. Plain-text assignment origin is not authenticated. Diagnostic grammar and simulator dialect coverage are incomplete.

For a suspected vulnerability, contact the maintainer through the GitHub profile and arrange a private channel before sharing sensitive details. Use a synthetic reproduction whenever possible. This early prototype has no service-level or production-safety guarantees.

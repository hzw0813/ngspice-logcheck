"""Explicit normalized scalar-table review; never parses proprietary databases."""

import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import sys

from . import __version__
from .cli import read_bounded
from .tables import compare_tables, load_table_spec


def _number(value):
    return "unavailable" if value is None else repr(value)


def render_table_html(report):
    esc = lambda value: html.escape(str(value), quote=True)
    rows = []
    for item in report["rows"]:
        state = "New check failure" if item["regressed"] else "Now passes" if item["improved"] else "No pass/fail change"
        bounds = ", ".join(f"{key} {_number(value)}" for key, value in sorted(item["limits"].items()))
        note = "; ".join(item["notes"])
        rows.append("<tr>"
                    f"<td><strong>{esc(item['test'])}</strong><br>{esc(item['corner'])}<br><small>Point: {esc(item['point'])}</small></td>"
                    f"<td><strong>{esc(item['measurement'])}</strong><br>{esc(item['unit'])}<br><small>{esc(state)}</small></td>"
                    f"<td>{esc(bounds)}</td>"
                    f"<td>{esc(_number(item['baselineValue']))}<br><small>{esc(item['baselineReason'])}</small></td>"
                    f"<td>{esc(_number(item['candidateValue']))}<br><small>{esc(item['candidateReason'])}</small></td>"
                    f"<td>{esc(_number(item['delta']))}<br><small>{esc(note)}</small></td></tr>")
    fingerprints = "".join(f"<dt>{esc(key)}</dt><dd>{esc(value)}</dd>" for key, value in report["inputs"].items())
    limitations = "".join(f"<li>{esc(item)}</li>" for item in report["limitations"])
    outcome = "Candidate checks pass" if report["passed"] else "Candidate checks fail"
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Scalar result review</title><style>body{{font:16px/1.5 system-ui,sans-serif;background:#f2f5f4;color:#172b2b;margin:0}}main{{max-width:1300px;margin:32px auto;padding:32px;background:white}}h1{{font-size:34px;line-height:1.2}}.label{{font-weight:700;letter-spacing:.05em;color:#2e6b60}}.status{{border-left:5px solid #2e6b60;background:#e9f2ee;padding:18px}}table{{width:100%;table-layout:fixed;border-collapse:collapse;font-size:14px;font-variant-numeric:tabular-nums}}th,td{{padding:12px;text-align:left;vertical-align:top;border-bottom:1px solid #dbe5df;overflow-wrap:anywhere}}th{{background:#ecf2ef}}small{{font-size:12px;color:#4a625c}}section{{margin-top:30px}}dd{{font:12px/1.6 monospace;overflow-wrap:anywhere;margin:0 0 12px}}@media(max-width:700px){{main{{padding:16px;margin:12px auto}}table{{font-size:12px}}th,td{{padding:6px}}h1{{font-size:28px}}}}@media print{{main{{padding:0;margin:0}}body{{background:white}}}}</style>
<main><p class="label">SIMREVIEW · NORMALIZED SCALAR CSV</p><h1>Scalar result review</h1>
<p class="status"><strong>{outcome}</strong><br>{report['regressions']} new check failures · {report['improvements']} improvements</p>
<p>Baseline and candidate values are matched by test, corner, point and measurement. Units and limits are explicit. This reviews supplied tables; it does not verify native ADE exports, simulation completion, freshness or signoff.</p>
<table><thead><tr><th>Test / corner / point</th><th>Measurement / unit</th><th>Inclusive limits</th><th>Baseline</th><th>Candidate</th><th>Delta</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<section><h2>Input fingerprints</h2><p>SHA-256 identifies supplied bytes. It does not authenticate their source or establish a fresh simulation.</p><dl>{fingerprints}</dl></section>
<section><h2>Interpretation limits</h2><ul>{limitations}</ul></section></main></html>\n'''


def main(argv=None):
    parser = argparse.ArgumentParser(prog="simreview", description="Compare two explicitly normalized scalar CSV tables. Native ADE CSV mapping remains manual.")
    parser.add_argument("baseline", help="Normalized baseline CSV, maximum 16 MiB")
    parser.add_argument("candidate", help="Normalized candidate CSV, maximum 16 MiB")
    parser.add_argument("--spec", required=True, help="JSON table identities, units and limits, maximum 1 MiB")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--json-out")
    parser.add_argument("--html-out")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    try:
        outputs = [Path(p) for p in (args.json_out, args.html_out) if p is not None]
        inputs = {Path(p).resolve() for p in (args.baseline, args.candidate, args.spec)}
        if len({p.resolve() for p in outputs}) != len(outputs) or any(p.resolve() in inputs for p in outputs):
            raise ValueError("Report paths must be distinct from each other and the inputs.")
        if any(p.exists() or p.is_symlink() for p in outputs):
            raise ValueError("Report output already exists; choose a fresh path.")
        baseline = read_bounded(args.baseline, 16 * 1024 * 1024)
        candidate = read_bounded(args.candidate, 16 * 1024 * 1024)
        spec_bytes = read_bounded(args.spec, 1024 * 1024)
        spec = load_table_spec(spec_bytes.decode("utf-8-sig"))
        report = compare_tables(baseline.decode("utf-8-sig"), candidate.decode("utf-8-sig"), spec)
        report["tool"] = {"name": "simreview", "version": __version__}
        report["inputs"] = {"baselineCsvSha256": hashlib.sha256(baseline).hexdigest(), "candidateCsvSha256": hashlib.sha256(candidate).hexdigest(), "specSha256": hashlib.sha256(spec_bytes).hexdigest()}
        serialized = json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
        for filename, content in ((args.json_out, serialized), (args.html_out, render_table_html(report))):
            if filename is not None:
                descriptor = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(content)
        if args.format == "json":
            sys.stdout.write(serialized)
        else:
            print("PASS" if report["passed"] else "FAIL")
            print(f"{report['regressions']} new check failures; {report['improvements']} improvements")
            for item in report["rows"]:
                # Do not place arbitrary table labels in terminal control sequences.
                identity = json.dumps([item[key] for key in ("test", "corner", "point", "measurement")], ensure_ascii=True)
                print(f"{identity}: {item['candidateReason']}")
            print("Normalized CSV only; no native Cadence export, run freshness or signoff validation.")
        return 0 if report["passed"] else 1
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        if isinstance(error, OSError):
            message = "Cannot read an input or create a report. Use regular readable files and fresh report paths."
        elif isinstance(error, UnicodeError):
            message = "Inputs must be valid UTF-8 text."
        elif isinstance(error, RecursionError):
            message = "Input nesting exceeds the supported limit."
        else:
            message = str(error)
        print(f"simreview: {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

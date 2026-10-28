"""Compare two local logcheck reports and produce a portable review packet."""

import argparse
import html
import json
import os
from pathlib import Path
import sys

from .cli import read_bounded
from .compare import compare_reports
from .core import _unique_object, _reject_constant, _token_float


def display_number(value):
    return "unavailable" if value is None else repr(value)


def render_html(report):
    """Self-contained, escaped, printable report without raw logs or scripts."""
    escape = lambda value: html.escape(str(value), quote=True)
    rows = []
    for check in report["checks"]:
        if check["regressed"]:
            change = "New limit/evidence failure"
        elif check["improved"]:
            change = "Now meets supplied check"
        else:
            change = "No pass/fail change"
        bounds = ", ".join(f"{key} {display_number(value)}" for key, value in sorted(check["limits"].items()))
        notes = "; ".join(check["notes"])
        rows.append("<tr>"
                    f"<td><strong>{escape(check['name'])}</strong><br><small>{escape(change)}{escape('; ' + notes) if notes else ''}</small></td>"
                    f"<td>{escape(bounds)}</td>"
                    f"<td>{escape(display_number(check['baselineValue']))}<br><small>{escape(check['baselineStatus'])}</small></td>"
                    f"<td>{escape(display_number(check['candidateValue']))}<br><small>{escape(check['candidateStatus'])}</small></td>"
                    f"<td>{escape(display_number(check['delta']))}</td></tr>")
    diagnostics = []
    for label, field in (("Baseline", "baselineDiagnostics"), ("Candidate", "candidateDiagnostics")):
        for entry in report[field]:
            diagnostics.append(f"<li>{label}: {escape(entry['severity'])} / {escape(entry['code'])} / log line {escape(entry['line'])}</li>")
    fingerprints = "".join(f"<h3>{escape(label)}</h3><dl><dt>Log SHA-256</dt><dd>{escape(ids['logSha256'])}</dd><dt>Spec SHA-256</dt><dd>{escape(ids['specSha256'])}</dd></dl>" for label, ids in report["inputs"].items())
    limits = "".join(f"<li>{escape(item)}</li>" for item in report["limitations"])
    status = "Supplied candidate checks pass" if report["passed"] else "Supplied candidate checks fail"
    return f'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; base-uri 'none'; form-action 'none'">
<title>Simulation result comparison</title>
<style>body{{font:16px/1.55 system-ui,sans-serif;color:#18252b;background:#f4f6f5;margin:0}}main{{max-width:1240px;margin:36px auto;padding:32px;background:white}}h1{{font-size:32px;line-height:1.2}}.eyebrow{{color:#356359;font-weight:700}}.status{{background:#eaf1ed;padding:18px;border-left:5px solid #356359}}.table{{overflow:auto}}table{{border-collapse:collapse;width:100%;table-layout:fixed;font-size:14px;font-variant-numeric:tabular-nums}}th,td{{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid #dce4e1;overflow-wrap:anywhere}}th{{background:#edf2ef}}small{{color:#4c6259;font-size:12px}}dd{{font:12px/1.6 monospace;overflow-wrap:anywhere;margin:0 0 12px}}section{{margin-top:32px}}@media(max-width:600px){{main{{padding:18px;margin:12px auto}}th,td{{padding:6px}}table{{font-size:12px}}}}@media print{{body{{background:white}}main{{margin:0;padding:0}}th,td{{padding:6px}}}}</style>
<main><p class="eyebrow">NGSPICE-LOGCHECK · LOCAL REVIEW PACKET</p><h1>Simulation result comparison</h1>
<p class="status"><strong>{status}</strong><br>{report['regressions']} new measurement failures · {report['improvements']} improvements<br>Global diagnostics are listed separately.</p>
<p>One supplied baseline report and one candidate report, with matching measurement bounds. Deltas describe numeric changes in the input's native units; they do not assess whether a change is physically better. Passing checks do not establish circuit correctness, run freshness, or signoff.</p>
<div class="table"><table><thead><tr><th>Measurement / change</th><th>Inclusive limits</th><th>Baseline</th><th>Candidate</th><th>Delta</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<section><h2>Log diagnostics</h2><ul>{''.join(diagnostics) or '<li>No recognized diagnostics recorded in the supplied reports.</li>'}</ul></section>
<section><h2>Input fingerprints</h2><p>These identify supplied bytes. They do not authenticate the simulator, timestamp, or report author.</p>{fingerprints}</section>
<section><h2>Interpretation limits</h2><ul>{limits}</ul></section></main></html>\n'''


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ngspice-logcheck compare", description="Compare two local logcheck JSON reports with the same measurement bounds.")
    parser.add_argument("baseline")
    parser.add_argument("candidate")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--json-out")
    parser.add_argument("--html-out")
    args = parser.parse_args(argv)
    try:
        output_names = [p for p in (args.json_out, args.html_out) if p is not None]
        resolved = [Path(p).resolve() for p in output_names]
        if len(set(resolved)) != len(resolved) or any(p in {Path(args.baseline).resolve(), Path(args.candidate).resolve()} for p in resolved):
            raise ValueError("Report paths must be distinct from each other and the inputs.")
        if any(Path(p).exists() or Path(p).is_symlink() for p in output_names):
            raise ValueError("Report output already exists; choose a fresh path.")
        reports = [json.loads(read_bounded(p, 4 * 1024 * 1024).decode("utf-8-sig"), object_pairs_hook=_unique_object, parse_constant=_reject_constant, parse_float=_token_float) for p in (args.baseline, args.candidate)]
        report = compare_reports(*reports)
        serialized = json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
        for filename, content in ((args.json_out, serialized), (args.html_out, render_html(report))):
            if filename is not None:
                descriptor = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(content)
        if args.format == "json":
            sys.stdout.write(serialized)
        else:
            print("PASS" if report["passed"] else "FAIL")
            print(f"{report['regressions']} new measurement failures; {report['improvements']} improvements")
            for check in report["checks"]:
                print(f"{check['name']}: {display_number(check['baselineValue'])} -> {display_number(check['candidateValue'])}; delta {display_number(check['delta'])}; {check['candidateStatus']}")
            print("Comparison applies to supplied report data; no run freshness or signoff claim.")
        return 0 if report["passed"] else 1
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        if isinstance(error, OSError):
            message = "Cannot read an input or create a report. Use readable regular files and fresh report paths."
        elif isinstance(error, UnicodeError):
            message = "Reports must be valid UTF-8 text."
        elif isinstance(error, (json.JSONDecodeError, RecursionError)):
            message = "Reports must contain bounded valid JSON."
        else:
            message = str(error)
        print(f"ngspice-logcheck compare: {message}", file=sys.stderr)
        return 2

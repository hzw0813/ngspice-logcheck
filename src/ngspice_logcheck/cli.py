"""Command line interface. No network, simulator, shell or netlist execution."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import xml.etree.ElementTree as ET

from . import __version__
from .core import check_log, load_spec

MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_SPEC_BYTES = 1024 * 1024


def read_bounded(filename, limit):
    """Read only a regular file, including when a caller supplies a FIFO."""
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(filename, flags)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Inputs must be regular files.")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Input exceeds the documented size limit.")
    return data


def xml_safe(value):
    # XML 1.0 excludes several characters that JSON and UTF-8 can contain.
    return "".join(c if c in "\t\n\r" or 0x20 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF else "?" for c in str(value))


def junit_xml(report):
    checks = report["checks"]
    diagnostics = [d for d in report["diagnostics"] if d["severity"] == "error"]
    failures = sum(c["status"] != "passed" for c in checks) + len(diagnostics)
    suite = ET.Element("testsuite", name="ngspice-logcheck", tests=str(len(checks) + len(diagnostics)), failures=str(failures), errors="0")
    properties = ET.SubElement(suite, "properties")
    for key, value in report["inputs"].items():
        ET.SubElement(properties, "property", name=key, value=xml_safe(value))
    for check in checks:
        case = ET.SubElement(suite, "testcase", classname="measurement", name=xml_safe(check["name"]))
        if check["status"] != "passed":
            ET.SubElement(case, "failure", message=xml_safe(check["reason"]))
    for index, diagnostic in enumerate(diagnostics, 1):
        case = ET.SubElement(suite, "testcase", classname="log", name=f"{xml_safe(diagnostic['code'])}-{index}")
        ET.SubElement(case, "failure", message=f"{xml_safe(diagnostic['code'])} at log line {diagnostic['line']}")
    return ET.tostring(suite, encoding="unicode", xml_declaration=True) + "\n"


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "compare":
        from .comparison_cli import main as comparison_main
        return comparison_main(arguments[1:])
    parser = argparse.ArgumentParser(description="Check one existing ngspice log against required scalar measurement limits.")
    parser.add_argument("log", help="UTF-8 combined simulator log (maximum 16 MiB)")
    parser.add_argument("--spec", required=True, help="JSON limits file (maximum 1 MiB)")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="stdout format")
    parser.add_argument("--json-out", help="Create a JSON report; path must not exist")
    parser.add_argument("--junit-out", help="Create a JUnit report; path must not exist")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(arguments)
    try:
        outputs = [Path(p) for p in (args.json_out, args.junit_out) if p is not None]
        inputs = {Path(args.log).resolve(), Path(args.spec).resolve()}
        if len({p.resolve() for p in outputs}) != len(outputs) or any(p.resolve() in inputs for p in outputs):
            raise ValueError("Report paths must be distinct from each other and the inputs.")
        if any(p.exists() or p.is_symlink() for p in outputs):
            raise ValueError("Report output already exists; choose a fresh path.")
        log_bytes = read_bounded(args.log, MAX_LOG_BYTES)
        spec_bytes = read_bounded(args.spec, MAX_SPEC_BYTES)
        spec = load_spec(spec_bytes.decode("utf-8-sig"))
        report = check_log(log_bytes.decode("utf-8-sig"), spec)
        report["tool"] = {"name": "ngspice-logcheck", "version": __version__}
        report["inputs"] = {"logSha256": hashlib.sha256(log_bytes).hexdigest(), "specSha256": hashlib.sha256(spec_bytes).hexdigest()}
        serialized = json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
        artifacts = [(args.json_out, serialized), (args.junit_out, junit_xml(report))]
        for filename, content in artifacts:
            if filename is not None:
                descriptor = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(content)
        if args.format == "json":
            sys.stdout.write(serialized)
        else:
            print("PASS" if report["passed"] else "FAIL")
            for check in report["checks"]:
                print(f"{check['status'].upper()} {check['name']}: {check['reason']}")
            for diagnostic in report["diagnostics"]:
                print(f"{diagnostic['severity'].upper()} line {diagnostic['line']}: {diagnostic['code']}")
            print("Checks apply only to supplied log values and limits; no simulation freshness or circuit-correctness claim.")
        return 0 if report["passed"] else 1
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        # Do not echo raw log/spec contents or local paths into CI logs.
        if isinstance(error, OSError):
            message = "Cannot read an input or create a report. Use regular readable files and fresh report paths."
        elif isinstance(error, UnicodeError):
            message = "Inputs must be valid UTF-8 text."
        elif isinstance(error, RecursionError):
            message = "JSON nesting exceeds the supported limit."
        else:
            message = str(error)
        print(f"ngspice-logcheck: {message}", file=sys.stderr)
        return 2

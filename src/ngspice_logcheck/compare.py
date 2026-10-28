"""Conservative comparison of two supplied ngspice-logcheck report artifacts.

Comparison validates the supplied scalar data and recomputes outcomes. It does
not authenticate reports or verify that their hashes describe real inputs.
"""

from __future__ import annotations

import math
import re
from typing import Any

from .core import _LIMITATIONS, _validate_spec

_HASH = re.compile(r"[0-9a-fA-F]{64}", re.ASCII)
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*", re.ASCII)
_CHECK_FIELDS = {"name", "status", "value", "limits", "lineNumbers", "reason"}
_REPORT_FIELDS = {"schemaVersion", "passed", "checks", "diagnostics", "limitations", "inputs"}
_FAILURE_REASONS = {"missing-measurement", "invalid-value", "ambiguous-duplicates", "measurement-failed"}
_NUMERIC_REASONS = {"within-limits", "below-minimum", "above-maximum"}
_DIAGNOSTIC_SEVERITIES = {
    "empty-log": "error",
    "measurement-failed": "error",
    "ngspice-fatal-error": "error",
    "ngspice-error": "error",
    "simulation-aborted": "error",
    "simulation-interrupted": "error",
    "timestep-too-small": "error",
    "ngspice-warning": "warning",
}


def _finite_value(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Report scalar values must be finite numbers or null.")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError("Report scalar values must be finite numbers or null.") from exc
    if not math.isfinite(number):
        raise ValueError("Report scalar values must be finite numbers or null.")
    return number


def _inputs(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"logSha256", "specSha256"}:
        raise ValueError("Report inputs require only logSha256 and specSha256 identifiers.")
    if any(not isinstance(item, str) or _HASH.fullmatch(item) is None for item in value.values()):
        raise ValueError("Report input identifiers must be 64 hexadecimal characters.")
    return {key: value[key].lower() for key in ("logSha256", "specSha256")}


def _diagnostics(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 100_000:
        raise ValueError("Report diagnostics must be a bounded list.")
    normalized = []
    for diagnostic in value:
        if not isinstance(diagnostic, dict) or set(diagnostic) != {"line", "severity", "code"}:
            raise ValueError("Report diagnostic fields are invalid.")
        code = diagnostic["code"]
        severity = diagnostic["severity"]
        line = diagnostic["line"]
        if not isinstance(code, str) or code not in _DIAGNOSTIC_SEVERITIES:
            raise ValueError("Report diagnostic code is unsupported.")
        if severity != _DIAGNOSTIC_SEVERITIES[code]:
            raise ValueError("Report diagnostic severity does not match its code.")
        if type(line) is not int or line < 0:
            raise ValueError("Report diagnostic line must be a nonnegative integer.")
        normalized.append({"line": line, "severity": severity, "code": code})
    return normalized


def _check(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _CHECK_FIELDS:
        raise ValueError("Report measurement fields are incomplete or unsupported.")
    name = value["name"]
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise ValueError("Report measurement name is invalid.")
    if value["status"] not in ("passed", "failed"):
        raise ValueError("Report measurement status is invalid.")
    reason = value["reason"]
    if not isinstance(reason, str) or reason not in _FAILURE_REASONS | _NUMERIC_REASONS:
        raise ValueError("Report measurement reason is unsupported.")
    lines = value["lineNumbers"]
    if not isinstance(lines, list) or len(lines) > 100_000 or any(type(line) is not int or line <= 0 for line in lines):
        raise ValueError("Report measurement lines must be positive integers.")
    if lines != sorted(set(lines)):
        raise ValueError("Report measurement lines must be sorted and unique.")
    number = _finite_value(value["value"])
    # These are observation-boundary facts in the artifact, not a trusted
    # outcome flag. Retain failure conservatively instead of turning null or
    # an explicitly failed measurement into numeric pass evidence.
    if reason == "missing-measurement" and (number is not None or lines):
        raise ValueError("Missing-measurement evidence is inconsistent.")
    if reason == "invalid-value" and (number is not None or len(lines) != 1):
        raise ValueError("Invalid-value evidence is inconsistent.")
    if reason == "ambiguous-duplicates" and (number is not None or len(lines) < 2):
        raise ValueError("Duplicate-measurement evidence is inconsistent.")
    if reason == "measurement-failed" and not lines:
        raise ValueError("Failed-measurement evidence needs an observed line.")
    if reason in _NUMERIC_REASONS and (number is None or len(lines) != 1):
        raise ValueError("Numeric measurement evidence is incomplete.")
    limits = _validate_spec({"schemaVersion": 1, "measurements": {name: value["limits"]}})["measurements"][name]
    if reason in _FAILURE_REASONS:
        recomputed_reason = reason
    elif "min" in limits and number < limits["min"]:
        recomputed_reason = "below-minimum"
    elif "max" in limits and number > limits["max"]:
        recomputed_reason = "above-maximum"
    else:
        recomputed_reason = "within-limits"
    return {"name": name, "value": number, "limits": limits, "status": "passed" if recomputed_reason == "within-limits" else "failed", "reason": recomputed_reason}


def _report(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not _REPORT_FIELDS.issubset(value) or not set(value).issubset(_REPORT_FIELDS | {"tool"}):
        raise ValueError("Report fields are incomplete or unsupported.")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise ValueError("Comparison supports report schemaVersion integer 1 only.")
    if type(value["passed"]) is not bool:
        raise ValueError("Report passed flag must be boolean; its claimed outcome is not trusted.")
    if "tool" in value:
        tool = value["tool"]
        if not isinstance(tool, dict) or set(tool) != {"name", "version"} or tool["name"] != "ngspice-logcheck" or not isinstance(tool["version"], str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+-]{0,63}", tool["version"], re.ASCII) is None:
            raise ValueError("Report tool metadata is invalid.")
    limitations = value["limitations"]
    if not isinstance(limitations, list) or len(limitations) > 100 or any(not isinstance(item, str) or len(item) > 4096 for item in limitations):
        raise ValueError("Report limitations must be a bounded list of strings.")
    checks = value["checks"]
    if not isinstance(checks, list) or not 1 <= len(checks) <= 1000:
        raise ValueError("Report checks must contain 1 to 1000 measurements.")
    normalized = {}
    for item in checks:
        check = _check(item)
        folded = check["name"].casefold()
        if folded in normalized:
            raise ValueError("Report measurement names must be unique without regard to case.")
        normalized[folded] = check
    diagnostics = _diagnostics(value["diagnostics"])
    passed = all(check["status"] == "passed" for check in normalized.values()) and not any(diagnostic["severity"] == "error" for diagnostic in diagnostics)
    return {"checks": normalized, "diagnostics": diagnostics, "passed": passed, "inputs": _inputs(value["inputs"])}


def _deltas(baseline: float | None, candidate: float | None) -> tuple[float | None, float | None, list[str]]:
    if baseline is None or candidate is None:
        return None, None, ["delta-unavailable-missing-value"]
    delta = candidate - baseline
    if not math.isfinite(delta):
        return None, None, ["delta-overflow", "relative-delta-unavailable-without-finite-delta"]
    if baseline == 0:
        return delta, None, ["relative-delta-undefined-zero-baseline"]
    relative = delta / baseline
    if not math.isfinite(relative):
        return delta, None, ["relative-delta-overflow"]
    if relative == 0 and delta != 0:
        return delta, None, ["relative-delta-underflow"]
    return delta, relative, []


def compare_reports(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Validate and compare same-metric/same-limit report artifacts.

    Claimed passed/status flags are validated for shape but recomputed from
    scalar values, explicit limits, conservative observation failures and safe
    diagnostics. Invalid or semantically incomparable reports raise ValueError.
    """
    before = _report(baseline)
    after = _report(candidate)
    if before["checks"].keys() != after["checks"].keys() or any(check["limits"] != after["checks"][name]["limits"] for name, check in before["checks"].items()):
        raise ValueError("Reports are incomparable: measurement names or limits changed.")
    checks = []
    for folded, left in before["checks"].items():
        right = after["checks"][folded]
        delta, relative, notes = _deltas(left["value"], right["value"])
        checks.append({
            "name": left["name"], "limits": dict(left["limits"]),
            "baselineValue": left["value"], "candidateValue": right["value"],
            "delta": delta, "relativeDelta": relative,
            "baselineStatus": left["status"], "candidateStatus": right["status"],
            "regressed": left["status"] == "passed" and right["status"] == "failed",
            "improved": left["status"] == "failed" and right["status"] == "passed",
            "baselineReason": left["reason"], "candidateReason": right["reason"], "notes": notes,
        })
    return {
        "schemaVersion": 1, "passed": after["passed"], "baselinePassed": before["passed"],
        "regressions": sum(check["regressed"] for check in checks), "improvements": sum(check["improved"] for check in checks),
        "inputs": {"baseline": dict(before["inputs"]), "candidate": dict(after["inputs"])},
        "checks": checks, "baselineDiagnostics": before["diagnostics"], "candidateDiagnostics": after["diagnostics"],
        "limitations": list(_LIMITATIONS) + [
            "This comparison validates supplied artifact structure and recomputes outcomes; it does not authenticate artifacts, recompute input hashes, or establish simulator completion, freshness, circuit correctness, or independent provenance.",
            "Hashes are user-controlled input identifiers. Equivalent measurement limits can have different spec-file hashes because bytes, formatting, or name casing differ.",
            "delta is candidate minus baseline in native units; relativeDelta is delta divided by baseline as a ratio, not a percentage. Delta fields are descriptive and do not define a performance-regression threshold.",
            "Regressed/improved count only per-measurement pass-to-fail/fail-to-pass transitions under unchanged limits. Global log errors affect overall outcomes and are reported separately from those counts.",
            "Recognized observation failure reasons remain failures even when a retained scalar is in range. Claimed passed/status flags and numeric summary reasons are not used as outcome authority.",
            "Null deltas mean a missing value, zero-baseline relative delta, or a binary64 arithmetic bound; fixed notes identify the reason. Raw report limitations and arbitrary source fields are not copied.",
        ],
    }

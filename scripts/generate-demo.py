"""Generate original simulator evidence and review artifacts. Never hand-edit results."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ngspice", required=True)
    parser.add_argument("--output", required=True, type=Path, help="New directory for generated artifacts")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    directory = args.output.resolve()
    version = subprocess.run([args.ngspice, "--version"], capture_output=True, text=True, timeout=20, check=True)
    provenance = {"generatedAt": datetime.now(timezone.utc).isoformat(), "simulatorVersion": version.stdout, "runs": [], "limitations": "Original passive RC examples. Inputs and hashes do not establish independent adoption or general simulator correctness."}
    for name, deck, expected in (("baseline", "rc.cir", 0), ("candidate", "rc-slower.cir", 1), ("failed-measure", "failed-measure.cir", 1)):
        circuit = ROOT / "examples" / deck
        result = subprocess.run([args.ngspice, "-n", "-b", str(circuit)], cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
        log = directory / f"{name}.log"
        log.write_bytes(result.stdout)
        report_path = directory / f"{name}.json"
        checked = subprocess.run([sys.executable, "-m", "ngspice_logcheck", str(log), "--spec", str(ROOT / "examples/limits.json"), "--json-out", str(report_path), "--junit-out", str(directory / f"{name}.xml")], capture_output=True, text=True, timeout=20)
        if checked.returncode != expected:
            raise RuntimeError(f"Unexpected {name} checker exit: {checked.returncode}; {checked.stderr}")
        provenance["runs"].append({"name": name, "circuit": f"examples/{deck}", "circuitSha256": hashlib.sha256(circuit.read_bytes()).hexdigest(), "simulatorArgs": ["-n", "-b", f"examples/{deck}"], "simulatorExitCode": result.returncode, "checkerExitCode": checked.returncode})
    compared = subprocess.run([sys.executable, "-m", "ngspice_logcheck", "compare", str(directory / "baseline.json"), str(directory / "candidate.json"), "--html-out", str(directory / "review.html"), "--json-out", str(directory / "comparison.json")], capture_output=True, text=True, timeout=20)
    if compared.returncode != 1:
        raise RuntimeError(f"Unexpected comparison exit {compared.returncode}; {compared.stderr}")
    provenance["comparisonExitCode"] = compared.returncode
    (directory / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"runs": provenance["runs"], "comparisonExitCode": compared.returncode, "output": str(directory)}, indent=2))


if __name__ == "__main__":
    main()

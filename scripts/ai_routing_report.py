"""Runs the Copilot routing tests and writes docs/ai-routing-test-report.md.

    .\\.venv\\Scripts\\python.exe scripts\\ai_routing_report.py

The twelve scenarios (``test_sNN`` in backend/tests/test_ai_routing.py) are listed first, each with the sentence the test
states; the rest of the routing tests follow in groups. Nothing here needs a database, a network or a model.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))

SCENARIOS = {
    "test_s01": "Simple greeting",
    "test_s02": "Straightforward dashboard metric",
    "test_s03": "Deterministic calculation",
    "test_s04": "Complex synthesis: local first, cloud only when enabled and permitted",
    "test_s05": "Cloud escalation disabled: no cloud request",
    "test_s06": "Sensitive data under a local-only rule: no cloud request",
    "test_s07": "Local model unavailable: graceful, no unauthorised fallback",
    "test_s08": "Invalid structured output: bounded retry, policy-controlled escalation",
    "test_s09": "Cloud budget exhausted: no further spending",
    "test_s10": "Unauthorised data request: rejected by backend permissions",
    "test_s11": "Destructive action: verified confirmation required",
    "test_s12": "Cloud timeout: bounded retry and graceful recovery",
}


def main() -> int:
    import test_ai_routing as module

    with tempfile.TemporaryDirectory() as folder:
        xml_path = Path(folder) / "routing.xml"
        run = subprocess.run(
            [sys.executable, "-m", "pytest", str(ROOT / "backend" / "tests" / "test_ai_routing.py"), "-q", f"--junitxml={xml_path}"],
            cwd=ROOT, capture_output=True, text=True,
        )
        cases = []
        for case in ET.parse(xml_path).getroot().iter("testcase"):
            status = "failed" if case.find("failure") is not None or case.find("error") is not None else "skipped" if case.find("skipped") is not None else "passed"
            klass = case.get("classname", "").split(".")[-1]
            name = case.get("name", "")
            method = getattr(getattr(module, klass, None), name.split("[")[0], None)
            doc_lines = ((method.__doc__ if method else "") or "").strip().splitlines()
            doc = doc_lines[0] if doc_lines else ""
            cases.append((klass, name, status, float(case.get("time", 0)), doc))

    lines = [
        "# AI Copilot routing: test report",
        "",
        f"Generated {datetime.now():%d %B %Y, %H:%M} by `scripts/ai_routing_report.py`. Providers are stand-ins that count what they were sent, so each scenario",
        "checks not only the answer but what was sent where. No database, network or model is needed.",
        "",
        "## The twelve scenarios",
        "",
        "| # | Scenario | Result | What the test checks |",
        "|---|---|---|---|",
    ]
    for key, title in SCENARIOS.items():
        found = next((c for c in cases if c[1].startswith(key)), None)
        lines.append(f"| {key[-2:].lstrip('0') or '0'} | {title} | {found[2].upper() if found else 'MISSING'} | {found[4] if found else ''} |")
    lines += [
        "",
        "Scenarios 1 to 3 go one step further than \"use the local model\": the application answers a greeting, a dashboard figure or a calculation by itself,",
        "with no model at all, so they cost nothing and work even when the local model is not installed.",
    ]
    others: dict[str, list[tuple]] = {}
    for klass, name, status, seconds, doc in cases:
        if not name.startswith("test_s") or klass != "Scenarios":
            others.setdefault(klass, []).append((name, status, doc))
    lines += ["", "## Everything else in the routing tests", ""]
    for klass, rows in others.items():
        lines += [f"### {klass}", "", "| Test | Result |", "|---|---|"]
        lines += [f"| {name.replace('test_', '').replace('_', ' ')} | {status.upper()} |" for name, status, _doc in rows]
        lines.append("")
    total = len(cases)
    passed = sum(1 for c in cases if c[2] == "passed")
    lines.insert(4, f"**{passed} of {total} routing tests passed.**")
    lines.insert(5, "")
    (ROOT / "docs" / "ai-routing-test-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{passed} of {total} passed; report written to docs/ai-routing-test-report.md")
    if run.returncode:
        print(run.stdout[-2000:])
    return run.returncode


if __name__ == "__main__":
    raise SystemExit(main())

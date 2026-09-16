"""Small pytest plugin for deterministic per-node qualification manifests."""
import json
import os
import re
from pathlib import Path

_reports = {}


def pytest_configure(config):
    global _reports
    _reports = {}


def pytest_runtest_logreport(report):
    if report.when != "call":
        return
    outcome = report.outcome
    if outcome not in {"passed", "failed", "skipped"}:
        return
    signature = ""
    if outcome == "failed":
        signature = re.sub(r"\s+", " ", str(report.longrepr)).strip()
    _reports[report.nodeid] = {
        "nodeid": report.nodeid,
        "outcome": outcome,
        **({"failure_signature": signature} if outcome == "failed" else {}),
    }


def pytest_sessionfinish(session, exitstatus):
    destination = os.environ.get("BYTE_PYTEST_MANIFEST")
    if not destination:
        return
    nodes = [_reports[k] for k in sorted(_reports)]
    counts = {o: sum(n["outcome"] == o for n in nodes) for o in ("passed", "failed", "skipped")}
    payload = {
        "predecessor_sha": os.environ.get("BYTE_PREDECESSOR_SHA", ""),
        "collected_count": len(nodes),
        "passed_count": counts["passed"],
        "failed_count": counts["failed"],
        "skipped_count": counts["skipped"],
        "nodes": nodes,
    }
    Path(destination).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

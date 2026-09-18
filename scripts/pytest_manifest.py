"""Small pytest plugin for deterministic per-node qualification manifests."""

import json
import os
import re
from pathlib import Path

_reports = {}
OUTCOMES = {"passed", "failed", "skipped"}
SIGNATURE_VERSION = "repo-root-v2"


def _normalize_signature(value):
    root = os.path.normcase(os.path.abspath(os.getcwd())).replace("/", "\\").rstrip("\\")
    text = re.sub(r"\s+", " ", str(value)).strip()
    for variant in (root.replace("\\", "\\\\"), root):
        text = re.sub(re.escape(variant), "<REPO>", text, flags=re.IGNORECASE)
    return text


def validate_manifest(payload, expected_sha=None):
    required = {
        "predecessor_sha",
        "signature_version",
        "collected_count",
        "passed_count",
        "failed_count",
        "skipped_count",
        "nodes",
    }
    if not isinstance(payload, dict) or not required.issubset(payload):
        raise ValueError("malformed pytest manifest")
    if expected_sha is not None and payload["predecessor_sha"] != expected_sha:
        raise ValueError("predecessor SHA mismatch")
    nodes = payload["nodes"]
    nodeids = {n.get("nodeid") for n in nodes if isinstance(n, dict)}
    if not isinstance(nodes, list) or len(nodeids) != len(nodes):
        raise ValueError("duplicate or malformed node records")
    counts = {o: 0 for o in OUTCOMES}
    for node in nodes:
        if (
            not isinstance(node, dict)
            or not isinstance(node.get("nodeid"), str)
            or node.get("outcome") not in OUTCOMES
        ):
            raise ValueError("malformed node record")
        counts[node["outcome"]] += 1
        if node["outcome"] == "failed" and not node.get("failure_signature"):
            raise ValueError("failed node lacks failure signature")
    if payload["collected_count"] != len(nodes) or any(
        payload[f"{o}_count"] != counts[o] for o in OUTCOMES
    ):
        raise ValueError("manifest counts inconsistent")
    return payload


def compare_manifests(baseline, candidate):
    validate_manifest(baseline)
    validate_manifest(candidate)
    if baseline["signature_version"] != candidate["signature_version"]:
        raise ValueError("signature normalization version mismatch")
    current = {n["nodeid"]: n for n in candidate["nodes"]}
    for node in baseline["nodes"]:
        actual = current.get(node["nodeid"])
        if actual is None or actual["outcome"] != node["outcome"]:
            raise ValueError(f"predecessor outcome mismatch: {node['nodeid']}")
        if (
            node["outcome"] == "failed"
            and actual["failure_signature"] != node["failure_signature"]
        ):
            raise ValueError(f"failure signature drift: {node['nodeid']}")
    inherited = {n["nodeid"] for n in baseline["nodes"]}
    extras = [
        n["nodeid"]
        for n in candidate["nodes"]
        if n["nodeid"] not in inherited and n["outcome"] == "failed"
    ]
    if extras:
        raise ValueError(f"candidate-only failures: {', '.join(extras)}")
    return True


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
        signature = _normalize_signature(report.longrepr)
    record = {
        "nodeid": report.nodeid,
        "outcome": outcome,
        **({"failure_signature": signature} if outcome == "failed" else {}),
    }
    if report.nodeid in _reports and _reports[report.nodeid] != record:
        raise RuntimeError(f"inconsistent duplicate report: {report.nodeid}")
    _reports[report.nodeid] = record


def pytest_sessionfinish(session, exitstatus):
    destination = os.environ.get("BYTE_PYTEST_MANIFEST")
    if not destination:
        return
    nodes = [_reports[k] for k in sorted(_reports)]
    counts = {
        o: sum(n["outcome"] == o for n in nodes)
        for o in ("passed", "failed", "skipped")
    }
    payload = {
        "predecessor_sha": os.environ.get("BYTE_PREDECESSOR_SHA", ""),
        "signature_version": SIGNATURE_VERSION,
        "collected_count": len(nodes),
        "passed_count": counts["passed"],
        "failed_count": counts["failed"],
        "skipped_count": counts["skipped"],
        "nodes": nodes,
    }
    Path(destination).write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )

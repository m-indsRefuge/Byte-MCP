"""Provider-free N05 NVIDIA qualification runner."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any

from byte_mcp.nvidia.qualification import inspect_nvidia_readiness, qualify_nvidia_offline

SCHEMA_VERSION = "nvidia-n05-offline-qualification-v1"

REQUIRED_FAILURE_IDS = tuple(f"F{number:02d}" for number in range(1, 21))

REQUIRED_COVERAGE_FILES = (
    "tests/nvidia/test_chat_execution.py",
    "tests/nvidia/test_chat_response.py",
    "tests/nvidia/test_errors_platform.py",
    "tests/nvidia/test_models.py",
    "tests/nvidia/test_n01_security_invariants.py",
    "tests/nvidia/test_n02_security_invariants.py",
    "tests/nvidia/test_platform_security_invariants.py",
    "tests/nvidia/test_qualification.py",
    "tests/nvidia/test_query_audit.py",
    "tests/nvidia/test_query_mcp.py",
    "tests/nvidia/test_query_protocol.py",
    "tests/nvidia/test_query_service.py",
    "tests/nvidia/test_review_evidence.py",
    "tests/nvidia/test_review_mcp.py",
    "tests/nvidia/test_review_protocol.py",
    "tests/nvidia/test_review_service_transmit.py",
    "tests/test_nvidia_runtime_integration.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_identifiers(path: Path) -> tuple[set[str], str, ast.AST]:
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id.lower())
        elif isinstance(node, ast.Attribute):
            names.add(node.attr.lower())
    return names, source, tree


def _server_has_static_nvidia_import(path: Path) -> bool:
    _, _, tree = _source_identifiers(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any("nvidia" in alias.name.lower() for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and "nvidia" in (node.module or "").lower():
            return True
    return False


def _governance_checks(repo_root: Path) -> dict[str, str]:
    query_path = repo_root / "src/byte_mcp/nvidia/query_service.py"
    server_path = repo_root / "src/byte_mcp/server.py"
    qualification_path = repo_root / "src/byte_mcp/nvidia/qualification.py"

    identifiers, query_source, query_tree = _source_identifiers(query_path)
    qualification_source = qualification_path.read_text(encoding="utf-8-sig")

    checks = {
        "query_no_while_loop": (
            "PASS"
            if not any(isinstance(node, ast.While) for node in ast.walk(query_tree))
            else "FAIL"
        ),
        "query_no_retry_identifier": (
            "PASS" if not any("retry" in name for name in identifiers) else "FAIL"
        ),
        "query_no_fallback_identifier": (
            "PASS" if not any("fallback" in name for name in identifiers) else "FAIL"
        ),
        "query_no_catalog_identifier": (
            "PASS" if not any("catalog" in name for name in identifiers) else "FAIL"
        ),
        "query_no_dynamic_model_discovery": (
            "PASS" if "/v1/models" not in query_source else "FAIL"
        ),
        "server_no_static_nvidia_import": (
            "PASS" if not _server_has_static_nvidia_import(server_path) else "FAIL"
        ),
        "qualification_no_hosted_settings_loader": (
            "PASS" if "NvidiaHostedSettings" not in qualification_source else "FAIL"
        ),
    }
    return checks


def _failure_map_checks(repo_root: Path) -> tuple[dict[str, str], str]:
    path = repo_root / "FAILURE_MAP.md"
    text = path.read_text(encoding="utf-8")

    checks: dict[str, str] = {}
    for failure_id in REQUIRED_FAILURE_IDS:
        checks[f"failure_map_{failure_id.lower()}"] = (
            "PASS" if f"| {failure_id} |" in text else "FAIL"
        )

    for relative in REQUIRED_COVERAGE_FILES:
        checks[f"coverage_file_{Path(relative).name}"] = (
            "PASS" if (repo_root / relative).is_file() else "FAIL"
        )

    return checks, _sha256(path)


def build_report(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()

    offline = qualify_nvidia_offline()
    readiness = inspect_nvidia_readiness().to_dict()

    checks = _governance_checks(repo_root)
    failure_checks, failure_map_sha256 = _failure_map_checks(repo_root)
    checks.update(failure_checks)

    checks["offline_qualification"] = (
        "PASS" if offline.get("status") == "PASS" and offline.get("provider_calls") == 0 else "FAIL"
    )
    checks["mcp_surface_exact"] = (
        "PASS"
        if tuple(readiness["expected_mcp_surface_names"])
        == ("nvidia_get_review", "nvidia_query", "nvidia_review")
        else "FAIL"
    )
    checks["credential_validation_deferred"] = (
        "PASS" if readiness.get("credential_status") == "DEFERRED_TO_TRANSMIT" else "FAIL"
    )
    checks["query_models_offline_qualified"] = (
        "PASS"
        if readiness.get("query_qualification")
        == {
            "deepseek-v4-pro": "OFFLINE_QUALIFIED",
            "lightning": "OFFLINE_QUALIFIED",
        }
        else "FAIL"
    )

    status = "PASS" if all(value == "PASS" for value in checks.values()) else "FAIL"

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "provider_calls": 0,
        "default_query_alias": readiness["default_query_alias"],
        "query_qualification": readiness["query_qualification"],
        "expected_mcp_surface_names": list(readiness["expected_mcp_surface_names"]),
        "credential_status": readiness["credential_status"],
        "failure_map_sha256": failure_map_sha256,
        "checks": dict(sorted(checks.items())),
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run provider-free NVIDIA N05 offline qualification."
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = build_report(args.repo_root)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)

    if args.output is not None:
        _write_report(args.output, report)

    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

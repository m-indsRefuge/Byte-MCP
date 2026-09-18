from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path("src/byte_mcp")
LEGACY_MARKERS = (
    "ox_v2_lifetime_probe",
    "ox_continue",
    "ox_revalidate",
    "OXProviderJobManager",
    "claim_retry_transmission",
    "recover_orphaned",
)
LEGACY_OX_FILENAMES = {
    "_natural_service_q03g.py",
    "_service_q03g.py",
    "bundles.py",
    "jobs.py",
    "natural_service.py",
    "protocol.py",
    "repositories.py",
}
LEGACY_IMPORT_PREFIXES = (
    "byte_mcp.ox_v2",
    "byte_mcp.ox._natural_service_q03g",
    "byte_mcp.ox._service_q03g",
    "byte_mcp.ox.bundles",
    "byte_mcp.ox.jobs",
    "byte_mcp.ox.natural_service",
    "byte_mcp.ox.protocol",
    "byte_mcp.ox.repositories",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    return imported


def test_legacy_ox_execution_markers_are_absent_from_active_source() -> None:
    violations: list[str] = []

    for path in sorted(SRC_ROOT.rglob("*.py")):
        relative = path.relative_to(SRC_ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for marker in LEGACY_MARKERS:
            if marker in text:
                violations.append(f"{relative}: {marker}")

    assert violations == []


def test_legacy_ox_module_set_is_absent() -> None:
    ox_root = SRC_ROOT / "ox"
    present = {path.name for path in ox_root.glob("*.py")} if ox_root.exists() else set()

    assert present.isdisjoint(LEGACY_OX_FILENAMES)


def test_abandoned_ox_v2_package_is_absent() -> None:
    assert not (SRC_ROOT / "ox_v2").exists()


def test_active_source_does_not_import_archived_ox_execution_modules() -> None:
    violations: list[str] = []

    for path in sorted(SRC_ROOT.rglob("*.py")):
        relative = path.relative_to(SRC_ROOT).as_posix()
        for module in sorted(_imports(path)):
            if module.startswith(LEGACY_IMPORT_PREFIXES):
                violations.append(f"{relative}: {module}")

    assert violations == []

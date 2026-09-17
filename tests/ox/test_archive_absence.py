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

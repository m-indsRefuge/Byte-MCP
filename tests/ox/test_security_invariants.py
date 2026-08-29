import json
from pathlib import Path

import pytest

from byte_mcp.errors import (
    OXApprovalError,
    OXBundleError,
    OXConfigurationError,
    OXRepositoryError,
    OXScopeError,
    OXTransportError,
)
from byte_mcp.ox.evidence import EvidenceStore
from byte_mcp.ox.service import OXReviewService
from byte_mcp.ox.settings import OXSettings
from tests.ox.helpers import commit_files, create_repository
from tests.ox.test_review_service import (
    FakeAudit,
    RecordingClient,
    prepare,
    verification,
    write_registry,
)

SECRET = "SENTINEL-GATEWAY-KEY"


class BoundaryClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("forbidden request reached provider boundary")


class UnknownOutcomeClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        raise OXTransportError(attempt_outcome="OUTCOME_UNKNOWN")


def make_security_service(
    tmp_path: Path,
    client,
    *,
    evidence_root: Path | None = None,
    max_bundle_bytes: int = 100_000,
):
    repository_path, base, target = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)
    settings = OXSettings(
        SECRET,
        registry_path,
        evidence_root or tmp_path / "evidence",
        max_bundle_bytes=max_bundle_bytes,
    )
    store = EvidenceStore(settings.evidence_root)
    service = OXReviewService(settings, store, client, FakeAudit())
    return service, store, repository_path, base, target, registry_path


def establish_review(tmp_path: Path):
    client = RecordingClient()
    service, store, repository_path, base, target, registry = make_security_service(
        tmp_path, client
    )
    proposal = prepare(service, base, target)
    service.transmit_review(proposal["review_id"])
    return service, store, repository_path, base, target, registry, proposal["review_id"]


def assert_secret_absent(root: Path, *values: object) -> None:
    for value in values:
        assert SECRET not in json.dumps(value, ensure_ascii=False, default=str)
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_file():
            assert SECRET.encode() not in path.read_bytes()


@pytest.mark.parametrize("location", ["objective", "verification", "source"])
def test_configured_gateway_key_in_review_material_fails_closed_before_persistence(
    tmp_path: Path,
    location: str,
) -> None:
    client = BoundaryClient()
    service, store, repository_path, base, target, _ = make_security_service(tmp_path, client)
    objective = "Review the exact committed change."
    records = verification()

    if location == "objective":
        objective = f"Review this change. Credential accidentally copied: {SECRET}"
    elif location == "verification":
        records[0]["stdout"] = f"environment dump contained {SECRET}\n"
    else:
        target = commit_files(
            repository_path,
            {"src/credential_leak.py": f"TOKEN = {SECRET!r}\n".encode()},
            b"credential leak fixture",
        )

    with pytest.raises(OXBundleError):
        service.prepare_review(
            repository="fixture",
            subsystem="validation",
            target_commit=target,
            base_commit=base,
            objective=objective,
            verification=records,
        )

    assert client.calls == 0
    assert_secret_absent(store._root)


def test_configured_gateway_key_in_continuation_fails_before_thread_or_provider(
    tmp_path: Path,
) -> None:
    service, store, _, _, _, _, review_id = establish_review(tmp_path)
    before = service.get_review(review_id, view="thread")
    boundary = BoundaryClient()
    service._client = boundary

    with pytest.raises(OXBundleError):
        service.continue_message(review_id, f"Do not persist this credential: {SECRET}")

    assert boundary.calls == 0
    assert service.get_review(review_id, view="thread") == before
    assert_secret_absent(store._root)


def test_configured_gateway_key_in_adjudication_fails_before_local_persistence(
    tmp_path: Path,
) -> None:
    service, store, _, _, _, _, review_id = establish_review(tmp_path)
    before = service.get_review(review_id, view="adjudication")

    with pytest.raises(OXBundleError):
        service.adjudicate(
            review_id,
            [
                {
                    "finding_id": f"{review_id}-F001",
                    "status": "CONFIRMED",
                    "evidence": f"Credential accidentally copied: {SECRET}",
                    "reasoning_summary": "Do not persist the credential.",
                }
            ],
        )

    assert service.get_review(review_id, view="adjudication") == before
    assert_secret_absent(store._root)


@pytest.mark.parametrize("location", ["verification", "source"])
def test_configured_gateway_key_in_revalidation_fails_before_revalidation_persistence(
    tmp_path: Path,
    location: str,
) -> None:
    service, store, repository_path, _, target, _, review_id = establish_review(tmp_path)
    records = verification()
    remediation = commit_files(
        repository_path,
        {"src/alpha.py": b"value = 'remediated'\n"},
        b"remediation",
    )
    if location == "verification":
        records[0]["stderr"] = f"credential={SECRET}\n"
    else:
        remediation = commit_files(
            repository_path,
            {"src/credential_leak.py": f"TOKEN = {SECRET!r}\n".encode()},
            b"revalidation credential leak",
        )

    with pytest.raises(OXBundleError):
        service.prepare_revalidation(
            review_id,
            target_commit=remediation,
            base_commit=target,
            verification=records,
        )

    assert service.get_review(review_id, view="revalidation")["revalidations"] == []
    assert_secret_absent(store._root)


@pytest.mark.parametrize(
    ("case", "error_type"),
    [
        ("unknown-repository", OXRepositoryError),
        ("unknown-subsystem", OXScopeError),
        ("non-exact-commit", OXRepositoryError),
        ("missing-verification", OXBundleError),
        ("oversized-bundle", OXBundleError),
    ],
)
def test_invalid_review_preflight_never_reaches_provider(
    tmp_path: Path,
    case: str,
    error_type: type[Exception],
) -> None:
    client = BoundaryClient()
    max_bytes = 16_384 if case == "oversized-bundle" else 100_000
    service, store, _, base, target, _ = make_security_service(
        tmp_path,
        client,
        max_bundle_bytes=max_bytes,
    )
    arguments = {
        "repository": "fixture",
        "subsystem": "validation",
        "target_commit": target,
        "base_commit": base,
        "objective": "Review it.",
        "verification": verification(),
    }
    if case == "unknown-repository":
        arguments["repository"] = "missing"
    elif case == "unknown-subsystem":
        arguments["subsystem"] = "missing"
    elif case == "non-exact-commit":
        arguments["target_commit"] = "HEAD"
    elif case == "missing-verification":
        arguments["verification"] = []
    else:
        arguments["objective"] = "x" * 20_000

    with pytest.raises(error_type):
        service.prepare_review(**arguments)

    assert client.calls == 0
    assert_secret_absent(store._root)


def test_evidence_root_overlap_fails_before_provider_and_evidence_creation(tmp_path: Path) -> None:
    client = BoundaryClient()
    repository_path, base, target = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)
    evidence_root = repository_path / ".ox-evidence"
    settings = OXSettings(SECRET, registry_path, evidence_root)
    service = OXReviewService(settings, EvidenceStore(evidence_root), client, FakeAudit())

    with pytest.raises(OXConfigurationError):
        service.prepare_review(
            repository="fixture",
            subsystem="validation",
            target_commit=target,
            base_commit=base,
            objective="Review it.",
            verification=verification(),
        )

    assert client.calls == 0
    assert not evidence_root.exists()


def test_manifest_tamper_invalidates_approval_before_provider(tmp_path: Path) -> None:
    client = BoundaryClient()
    service, store, _, base, target, _ = make_security_service(tmp_path, client)
    proposal = prepare(service, base, target)
    manifest_path = store._root / "reviews" / proposal["review_id"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_count"] = 999
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises((OXApprovalError, OXBundleError)):
        service.transmit_review(proposal["review_id"])

    assert client.calls == 0
    assert_secret_absent(store._root, proposal)


def test_same_length_objective_tamper_invalidates_approval_before_provider(
    tmp_path: Path,
) -> None:
    client = BoundaryClient()
    service, store, _, base, target, _ = make_security_service(tmp_path, client)
    proposal = prepare(service, base, target)
    review_path = store._root / "reviews" / proposal["review_id"] / "review.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    original = review["objective"]
    replacement = "X" * len(original)
    assert replacement != original
    assert len(replacement.encode()) == len(original.encode())
    review["objective"] = replacement
    review_path.write_text(json.dumps(review), encoding="utf-8")

    with pytest.raises(OXApprovalError):
        service.transmit_review(proposal["review_id"])

    assert client.calls == 0
    assert_secret_absent(store._root, proposal)


def test_unknown_outcome_retry_and_revalidation_require_renewed_approval(tmp_path: Path) -> None:
    client = UnknownOutcomeClient()
    service, store, repository_path, base, target, _ = make_security_service(tmp_path, client)
    proposal = prepare(service, base, target)

    with pytest.raises(OXTransportError):
        service.transmit_review(proposal["review_id"])
    assert client.calls == 1

    with pytest.raises(OXApprovalError):
        service.retry_review(proposal["review_id"], renewed_approval=False)
    assert client.calls == 1

    safe_client = BoundaryClient()
    second_root = tmp_path / "second"
    service2, _, repository2, base2, target2, _ = make_security_service(second_root, safe_client)
    proposal2 = prepare(service2, base2, target2)
    remediation = commit_files(
        repository2,
        {"src/alpha.py": b"value = 'remediated'\n"},
        b"remediation",
    )
    with pytest.raises(OXApprovalError):
        service2.prepare_revalidation(
            proposal2["review_id"],
            target_commit=remediation,
            base_commit=target2,
            verification=verification(),
        )

    assert safe_client.calls == 0
    assert_secret_absent(store._root)

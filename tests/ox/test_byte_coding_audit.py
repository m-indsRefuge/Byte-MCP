import json
from pathlib import Path

import httpx
import pytest

from byte_mcp.errors import OXEvidenceError
from byte_mcp.ox.bundles import BundleBuilder
from byte_mcp.ox.client import OXClient
from byte_mcp.ox.evidence import EvidenceStore
from byte_mcp.ox.models import OXAvailability, ProviderUsage
from byte_mcp.ox.repositories import GitRepository, RepositoryRegistry
from byte_mcp.ox.settings import OXSettings
from tests.ox.helpers import create_repository
from tests.ox.test_repositories import write_registry


def _verification() -> list[dict[str, object]]:
    return [
        {
            "id": "verification-1",
            "kind": "pytest",
            "command": "python -m pytest",
            "exit_code": 0,
            "stdout": "passed\n",
            "stderr": "",
            "recorded_at": "2026-08-29T08:00:00Z",
            "provenance": "operator-supplied",
        }
    ]


def test_ox_availability_has_distinct_disabled_and_misconfigured_states() -> None:
    assert {state.value for state in OXAvailability} == {
        "AVAILABLE",
        "DISABLED",
        "MISCONFIGURED",
    }


def test_provider_usage_preserves_total_and_cached_input_tokens() -> None:
    usage = ProviderUsage(
        input_tokens=7,
        output_tokens=3,
        total_tokens=10,
        cached_input_tokens=1,
    )

    assert usage.total_tokens == 10
    assert usage.cached_input_tokens == 1


def test_client_honors_bounded_output_setting_and_preserves_complete_usage() -> None:
    requests: list[httpx.Request] = []
    settings = OXSettings(
        "SENTINEL-SECRET",
        Path("repositories.json"),
        Path("evidence"),
        max_output_tokens=2_048,
    )
    response = {
        "id": "chatcmpl-123",
        "model": "zai/glm-5.3-flash",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 7,
            "completion_tokens": 3,
            "total_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 1},
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=response)

    result = OXClient(settings, transport=httpx.MockTransport(handler)).complete(
        [{"role": "user", "content": "review"}],
        json_mode=False,
        attempt_id="OX-000001-A001",
    )

    assert json.loads(requests[0].content)["max_tokens"] == 2_048
    assert result.usage == ProviderUsage(
        input_tokens=7,
        output_tokens=3,
        total_tokens=10,
        cached_input_tokens=1,
    )


def test_diff_manifest_entry_hashes_the_raw_diff_artifact(tmp_path) -> None:
    repository_path, base, target = create_repository(tmp_path)
    registry_path = tmp_path / "repositories.json"
    write_registry(registry_path, repository_path)
    definition = RepositoryRegistry.load(registry_path).get("fixture")
    reader = GitRepository.open(definition)

    prepared = BundleBuilder(reader, max_bundle_bytes=100_000).prepare(
        definition.subsystems["validation"],
        target,
        base,
        _verification(),
    )

    assert prepared.diff is not None
    entry = next(
        item
        for item in prepared.manifest.entries
        if item.logical_path == "__ox__/base-to-target.diff"
    )
    assert entry.byte_length == prepared.diff.byte_length
    assert entry.sha256 == prepared.diff.sha256


def test_evidence_rejects_overlong_review_identity(tmp_path) -> None:
    store = EvidenceStore(tmp_path)

    with pytest.raises(OXEvidenceError, match="review identity is invalid"):
        store.persist_prepared_review(
            identity={"review_id": "OX-0000001"},
            manifest={"manifest_sha256": "a" * 64},
            bundle={"packet": "prepared"},
        )

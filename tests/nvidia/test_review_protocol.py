import importlib
import importlib.util
import json
from types import MappingProxyType

import pytest

from byte_mcp.nvidia.review_packet import (
    NvidiaReviewArtifact,
    NvidiaReviewManifest,
    NvidiaReviewManifestEntry,
    PreparedNvidiaReviewPacket,
)

MODEL_ID = "nvidia/nemotron-3.5-lightning-30b-a3b"
BASE = "1" * 40
TARGET = "2" * 40


def review_protocol_module():
    spec = importlib.util.find_spec("byte_mcp.nvidia.review_protocol")
    assert spec is not None, "NVIDIA review protocol module must exist"
    return importlib.import_module("byte_mcp.nvidia.review_protocol")


def packet() -> PreparedNvidiaReviewPacket:
    diff = NvidiaReviewArtifact(
        logical_path="__nvidia_review__/base-to-target.diff",
        categories=("diff",),
        byte_length=5,
        sha256="a" * 64,
        provider_text="diff\n",
    )
    artifact = NvidiaReviewArtifact(
        logical_path="src/a.py",
        categories=("source",),
        byte_length=10,
        sha256="b" * 64,
        provider_text="value = 1\n",
    )
    entries = (
        NvidiaReviewManifestEntry(
            logical_path=diff.logical_path,
            categories=diff.categories,
            byte_length=diff.byte_length,
            sha256=diff.sha256,
        ),
        NvidiaReviewManifestEntry(
            logical_path=artifact.logical_path,
            categories=artifact.categories,
            byte_length=artifact.byte_length,
            sha256=artifact.sha256,
        ),
    )
    manifest = NvidiaReviewManifest(
        repository_alias="fixture",
        subsystem_id="validation",
        base_commit=BASE,
        target_commit=TARGET,
        entries=entries,
        manifest_sha256="c" * 64,
    )
    serialized = json.dumps(
        {
            "repository_alias": "fixture",
            "subsystem_id": "validation",
            "base_commit": BASE,
            "target_commit": TARGET,
            "objective": "Review regression risk",
            "artifacts": [{"logical_path": "src/a.py", "provider_text": "value = 1\n"}],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return PreparedNvidiaReviewPacket(
        repository_alias="fixture",
        subsystem_id="validation",
        base_commit=BASE,
        target_commit=TARGET,
        objective="Review regression risk",
        diff=diff,
        artifacts=(artifact,),
        verification=(MappingProxyType({"id": "pytest", "sha256": "d" * 64}),),
        manifest=manifest,
        serialized_packet=serialized,
        total_bytes=len(serialized),
    )


def valid_finding(**overrides: object) -> dict[str, object]:
    finding: dict[str, object] = {
        "severity": "MEDIUM",
        "path": "src/a.py",
        "line": 1,
        "title": "Possible regression",
        "explanation": "The changed branch may return the wrong value.",
        "recommendation": "Add the missing guard and regression test.",
    }
    finding.update(overrides)
    return finding


def result_json(
    *,
    decision: str = "FINDINGS",
    summary: str = "One issue found.",
    findings: list[dict[str, object]] | None = None,
    **extra: object,
) -> str:
    payload: dict[str, object] = {
        "decision": decision,
        "summary": summary,
        "findings": [valid_finding()] if findings is None else findings,
    }
    payload.update(extra)
    return json.dumps(payload, separators=(",", ":"))


def test_review_request_is_deterministic_and_uses_fixed_thinking_off_controls() -> None:
    module = review_protocol_module()
    review_packet = packet()

    first = module.prepare_nvidia_review_request(review_packet)
    second = module.prepare_nvidia_review_request(review_packet)

    assert first.body_bytes == second.body_bytes
    assert first.request_sha256 == second.request_sha256
    body = json.loads(first.body_bytes)
    assert body["model"] == MODEL_ID
    assert body["temperature"] == 0.2
    assert body["top_p"] == 0.95
    assert body["max_tokens"] == 4096
    assert body["n"] == 1
    assert body["stream"] is False
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "reasoning_budget" not in body
    assert [message["role"] for message in body["messages"]] == ["system", "user"]
    assert review_packet.serialized_packet.decode("utf-8") in body["messages"][1]["content"]


def test_parser_accepts_bounded_findings_and_pass() -> None:
    module = review_protocol_module()
    parsed = module.parse_nvidia_review_result(
        result_json(),
        frozenset({"src/a.py"}),
    )
    assert parsed.decision == "FINDINGS"
    assert parsed.summary == "One issue found."
    assert parsed.findings[0].severity == "MEDIUM"
    assert parsed.findings[0].path == "src/a.py"

    passed = module.parse_nvidia_review_result(
        result_json(decision="PASS", summary="No defects found.", findings=[]),
        frozenset({"src/a.py"}),
    )
    assert passed.decision == "PASS"
    assert passed.findings == ()


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        result_json(extra="unexpected"),
        result_json(decision="MAYBE"),
        result_json(decision="PASS"),
        result_json(decision="FINDINGS", findings=[]),
    ],
)
def test_parser_rejects_malformed_unknown_or_inconsistent_results(content: str) -> None:
    module = review_protocol_module()
    with pytest.raises(module.NvidiaReviewResultError):
        module.parse_nvidia_review_result(content, frozenset({"src/a.py"}))


@pytest.mark.parametrize("severity", ["INFO", "medium", "", 1, None])
def test_parser_rejects_invalid_severity(severity: object) -> None:
    module = review_protocol_module()
    with pytest.raises(module.NvidiaReviewResultError):
        module.parse_nvidia_review_result(
            result_json(findings=[valid_finding(severity=severity)]),
            frozenset({"src/a.py"}),
        )


@pytest.mark.parametrize(
    "path",
    ["src/other.py", "../src/a.py", "/src/a.py", "C:/src/a.py", "src\\a.py", ""],
)
def test_parser_rejects_unprepared_or_unsafe_paths(path: str) -> None:
    module = review_protocol_module()
    with pytest.raises(module.NvidiaReviewResultError):
        module.parse_nvidia_review_result(
            result_json(findings=[valid_finding(path=path)]),
            frozenset({"src/a.py"}),
        )


@pytest.mark.parametrize("line", [0, -1, 2_147_483_648, True, "1"])
def test_parser_rejects_invalid_line(line: object) -> None:
    module = review_protocol_module()
    with pytest.raises(module.NvidiaReviewResultError):
        module.parse_nvidia_review_result(
            result_json(findings=[valid_finding(line=line)]),
            frozenset({"src/a.py"}),
        )


def test_parser_accepts_null_line() -> None:
    module = review_protocol_module()
    parsed = module.parse_nvidia_review_result(
        result_json(findings=[valid_finding(line=None)]),
        frozenset({"src/a.py"}),
    )
    assert parsed.findings[0].line is None


def test_parser_rejects_result_and_finding_bounds() -> None:
    module = review_protocol_module()
    allowed = frozenset({"src/a.py"})

    with pytest.raises(module.NvidiaReviewResultError):
        module.parse_nvidia_review_result(result_json(summary="x" * 4001), allowed)
    with pytest.raises(module.NvidiaReviewResultError):
        module.parse_nvidia_review_result(
            result_json(findings=[valid_finding()] * 51),
            allowed,
        )
    for field, value in (
        ("path", "p" * 513),
        ("title", "t" * 201),
        ("explanation", "e" * 4001),
        ("recommendation", "r" * 4001),
    ):
        with pytest.raises(module.NvidiaReviewResultError):
            module.parse_nvidia_review_result(
                result_json(findings=[valid_finding(**{field: value})]),
                allowed,
            )


def test_parser_rejects_unknown_finding_fields() -> None:
    module = review_protocol_module()
    finding = valid_finding()
    finding["confidence"] = 0.9
    with pytest.raises(module.NvidiaReviewResultError):
        module.parse_nvidia_review_result(
            result_json(findings=[finding]),
            frozenset({"src/a.py"}),
        )


def test_result_error_does_not_echo_provider_content() -> None:
    module = review_protocol_module()
    secret_text = "provider-secret-material"
    with pytest.raises(module.NvidiaReviewResultError) as caught:
        module.parse_nvidia_review_result(secret_text, frozenset({"src/a.py"}))
    assert secret_text not in str(caught.value)
    assert secret_text not in repr(caught.value)

import json

import pytest

from byte_mcp.errors import OXFindingValidationError
from byte_mcp.ox.models import FindingStatus
from byte_mcp.ox.protocol import build_initial_messages, parse_findings


def valid_payload() -> dict[str, object]:
    return {
        "protocol_version": "ox-findings-v1",
        "findings": [
            {
                "category": "correctness",
                "severity": "high",
                "confidence": 0.9,
                "location": "src/example.py:10",
                "claim": "The branch can return stale state.",
                "evidence": "The persisted state is read before the guarded transition.",
                "reproduction": "Issue two concurrent approvals.",
                "expected_behavior": "Exactly one approval reaches the provider boundary.",
                "observed_or_predicted_behavior": "Both approvals may proceed.",
                "disproof_condition": "Show an atomic claim before either provider call.",
                "recommended_investigation": "Exercise the approval race under a barrier.",
            }
        ],
    }


def test_build_initial_messages_uses_fixed_validator_mandate_and_packet_only() -> None:
    packet = {"protocol_version": "ox-review-v1", "manifest": {"manifest_sha256": "a" * 64}}

    messages = build_initial_messages(packet, objective="Check approval concurrency.")

    assert [message["role"] for message in messages] == ["system", "user"]
    assert "independent validator" in messages[0]["content"].lower()
    assert "falsifiable" in messages[0]["content"].lower()
    assert "disproof" in messages[0]["content"].lower()
    assert "ox-findings-v1" in messages[0]["content"]
    user_payload = json.loads(messages[1]["content"])
    assert user_payload == {
        "objective": "Check approval concurrency.",
        "review_packet": packet,
    }


def test_parse_findings_assigns_deterministic_local_ids_in_array_order() -> None:
    payload = valid_payload()
    payload["findings"].append(
        {
            **payload["findings"][0],
            "severity": "low",
            "claim": "A second claim.",
        }
    )

    findings = parse_findings(json.dumps(payload), "OX-000001")

    assert [finding.finding_id for finding in findings] == [
        "OX-000001-F001",
        "OX-000001-F002",
    ]
    assert findings[0].status is FindingStatus.RAISED
    assert findings[0].severity == "high"
    assert findings[0].confidence == 0.9
    assert findings[0].claim == "The branch can return stale state."
    assert findings[1].severity == "low"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(protocol_version="wrong"),
        lambda value: value.update(findings="not-a-list"),
        lambda value: value.update(extra="not-allowed"),
        lambda value: value["findings"][0].pop("disproof_condition"),
        lambda value: value["findings"][0].update(severity="urgent"),
        lambda value: value["findings"][0].update(confidence=1.1),
        lambda value: value["findings"][0].update(confidence=True),
        lambda value: value["findings"][0].update(location=["not", "text"]),
    ],
)
def test_parse_findings_rejects_malformed_schema_without_repair(mutation) -> None:
    payload = valid_payload()
    mutation(payload)
    content = json.dumps(payload)

    with pytest.raises(OXFindingValidationError):
        parse_findings(content, "OX-000001")

    assert content == json.dumps(payload)


def test_parse_findings_rejects_invalid_json_and_invalid_review_id() -> None:
    with pytest.raises(OXFindingValidationError):
        parse_findings("not json", "OX-000001")
    with pytest.raises(OXFindingValidationError):
        parse_findings(json.dumps(valid_payload()), "OX-0000001")

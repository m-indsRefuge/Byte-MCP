"""Provider-native OX review messages and local findings validation."""

import json
import math
import re
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass

from byte_mcp.errors import OXFindingValidationError, OXRequestError

from .models import Finding, FindingStatus

_FINDINGS_VERSION = "ox-findings-v1"
_REVIEW_ID = re.compile(r"^OX-\d{6}$")
_SEVERITIES = frozenset({"critical", "high", "medium", "low", "info"})
_REQUIRED_FINDING_FIELDS = (
    "category",
    "severity",
    "confidence",
    "location",
    "claim",
    "evidence",
    "reproduction",
    "expected_behavior",
    "observed_or_predicted_behavior",
    "disproof_condition",
    "recommended_investigation",
)

_SYSTEM_MANDATE = """You are OX, an independent engineering validator.
You are not the implementation authority. Review only the supplied evidence and make specific,
falsifiable claims. State uncertainty when evidence is insufficient instead of inventing facts.
Report only defects you can substantiate; do not criticize behavior that satisfies the supplied
contract or infer defects merely from missing external context.

For each defect, make the location, claim, supporting evidence, reproduction or demonstration,
expected behavior, and uncertainty clear enough for another engineer to evaluate independently.
Use clear natural text or Markdown. Do not force the response into JSON or another machine schema.
Do not request tools, execution, hidden reasoning, filesystem access, or material outside the
supplied review packet."""


def _json_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    return value


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            _json_value(value),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise OXRequestError(attempt_outcome="NOT_SENT") from exc


def build_initial_messages(
    bundle: Mapping[str, object], *, objective: str
) -> list[dict[str, str]]:
    if not isinstance(objective, str) or not objective.strip() or not isinstance(bundle, Mapping):
        raise OXRequestError(attempt_outcome="NOT_SENT")
    user_content = _canonical_json(
        {"objective": objective.strip(), "review_packet": _json_value(bundle)}
    )
    return [
        {"role": "system", "content": _SYSTEM_MANDATE},
        {"role": "user", "content": user_content},
    ]


def parse_findings(content: str, review_id: str) -> tuple[Finding, ...]:
    if not isinstance(content, str) or _REVIEW_ID.fullmatch(review_id) is None:
        raise OXFindingValidationError(attempt_outcome="COMPLETED")
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        raise OXFindingValidationError(attempt_outcome="COMPLETED") from None
    if not isinstance(payload, dict) or set(payload) != {"protocol_version", "findings"}:
        raise OXFindingValidationError(attempt_outcome="COMPLETED")
    invalid_container = payload["protocol_version"] != _FINDINGS_VERSION or not isinstance(
        payload["findings"], list
    )
    if invalid_container:
        raise OXFindingValidationError(attempt_outcome="COMPLETED")

    findings: list[Finding] = []
    for index, raw in enumerate(payload["findings"], start=1):
        if not isinstance(raw, dict) or set(raw) != set(_REQUIRED_FINDING_FIELDS):
            raise OXFindingValidationError(attempt_outcome="COMPLETED")
        severity = raw["severity"]
        confidence = raw["confidence"]
        if not isinstance(severity, str) or severity not in _SEVERITIES:
            raise OXFindingValidationError(attempt_outcome="COMPLETED")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, int | float)
            or not math.isfinite(float(confidence))
            or not 0 <= float(confidence) <= 1
        ):
            raise OXFindingValidationError(attempt_outcome="COMPLETED")
        textual = {field: raw[field] for field in _REQUIRED_FINDING_FIELDS if field != "confidence"}
        if any(not isinstance(value, str) or not value.strip() for value in textual.values()):
            raise OXFindingValidationError(attempt_outcome="COMPLETED")
        finding_id = f"{review_id}-F{index:03d}"
        findings.append(
            Finding(
                finding_id=finding_id,
                status=FindingStatus.RAISED,
                summary=str(raw["claim"]).strip(),
                category=str(raw["category"]).strip(),
                severity=severity,
                confidence=float(confidence),
                location=str(raw["location"]).strip(),
                claim=str(raw["claim"]).strip(),
                evidence=str(raw["evidence"]).strip(),
                reproduction=str(raw["reproduction"]).strip(),
                expected_behavior=str(raw["expected_behavior"]).strip(),
                observed_or_predicted_behavior=str(raw["observed_or_predicted_behavior"]).strip(),
                disproof_condition=str(raw["disproof_condition"]).strip(),
                recommended_investigation=str(raw["recommended_investigation"]).strip(),
            )
        )
    return tuple(findings)

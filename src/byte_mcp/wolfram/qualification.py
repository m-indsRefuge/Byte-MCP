"""Deterministic scoring model for the Wolfram LLM API qualification campaign."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_HARD_LABELS = frozenset(
    {"UNINTERPRETABLE", "API_ERROR", "TIMEOUT", "UNSUPPORTED_CLAIM", "FACTUALLY_WRONG"}
)


@dataclass(frozen=True, slots=True)
class QualificationTask:
    task_id: str
    family: str
    prompt: str
    ground_truth: str
    coding: bool = False


@dataclass(frozen=True, slots=True)
class QualificationScore:
    task_id: str
    correctness: int
    specificity: int
    evidence_quality: int
    engineering_usefulness: int
    unsupported_claim_discipline: int
    hard_label: str | None = None
    defect_found: bool | None = None
    root_cause_correct: bool | None = None
    location_correct: bool | None = None
    fix_correct: bool | None = None
    tests_useful: bool | None = None
    invented_facts: bool | None = None

    def __post_init__(self) -> None:
        for value in (
            self.correctness,
            self.specificity,
            self.evidence_quality,
            self.engineering_usefulness,
            self.unsupported_claim_discipline,
        ):
            if not isinstance(value, int) or not 0 <= value <= 4:
                raise ValueError("Qualification dimensions must be integers from 0 to 4.")
        if self.hard_label is not None and self.hard_label not in _HARD_LABELS:
            raise ValueError("Unknown qualification hard label.")


@dataclass(frozen=True, slots=True)
class QualificationSummary:
    overall_average: float
    family_averages: dict[str, float]
    classification_counts: dict[str, int]
    coding_root_cause_correct_rate: float | None
    unsupported_or_invented_rate: float
    primary_count: int


def campaign_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_campaign(path: Path) -> tuple[QualificationTask, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_tasks = payload.get("tasks")
    if payload.get("schema_version") != 1 or not isinstance(raw_tasks, list):
        raise ValueError("Invalid Wolfram qualification campaign.")
    tasks = tuple(QualificationTask(**item) for item in raw_tasks)
    ids = [task.task_id for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("Qualification task IDs must be unique.")
    return tasks


def score_total(score: QualificationScore) -> int:
    return (
        score.correctness
        + score.specificity
        + score.evidence_quality
        + score.engineering_usefulness
        + score.unsupported_claim_discipline
    )


def classify_total(total: int) -> str:
    if not 0 <= total <= 20:
        raise ValueError("Qualification total must be between 0 and 20.")
    if total >= 18:
        return "EXCELLENT"
    if total >= 14:
        return "USEFUL"
    if total >= 10:
        return "PARTIAL"
    if total >= 5:
        return "WEAK"
    return "NOT_USEFUL"


def summarize(scores: Sequence[QualificationScore]) -> QualificationSummary:
    if not scores:
        raise ValueError("At least one qualification score is required.")
    totals = [score_total(score) for score in scores]
    family_values: dict[str, list[int]] = defaultdict(list)
    coding_root: list[bool] = []
    unsupported = 0
    for score in scores:
        family = score.task_id.rsplit("-", 1)[0]
        family_values[family].append(score_total(score))
        if family in {"WA-04", "WA-05"} and score.root_cause_correct is not None:
            coding_root.append(score.root_cause_correct)
        if score.invented_facts is True or score.hard_label == "UNSUPPORTED_CLAIM":
            unsupported += 1
    counts = Counter(classify_total(total) for total in totals)
    return QualificationSummary(
        overall_average=sum(totals) / len(totals),
        family_averages={
            family: sum(values) / len(values) for family, values in sorted(family_values.items())
        },
        classification_counts=dict(sorted(counts.items())),
        coding_root_cause_correct_rate=(
            sum(coding_root) / len(coding_root) if coding_root else None
        ),
        unsupported_or_invented_rate=unsupported / len(scores),
        primary_count=len(scores),
    )


def broad_coengineer_threshold_met(
    summary: QualificationSummary,
    *,
    byte_plus_wolfram_improved: bool,
) -> bool:
    root_rate = summary.coding_root_cause_correct_rate
    return (
        summary.overall_average >= 14.0
        and root_rate is not None
        and root_rate >= 0.70
        and summary.unsupported_or_invented_rate <= 0.10
        and byte_plus_wolfram_improved
    )

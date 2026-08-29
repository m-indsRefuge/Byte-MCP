from collections import Counter
from pathlib import Path

import pytest

from byte_mcp.wolfram.qualification import (
    QualificationScore,
    broad_coengineer_threshold_met,
    campaign_sha256,
    classify_total,
    load_campaign,
    score_total,
    summarize,
)

CAMPAIGN = Path("qualification/wolfram/llm-api-v1.json")


def test_campaign_is_fixed_30_task_balanced_fixture() -> None:
    tasks = load_campaign(CAMPAIGN)
    assert len(tasks) == 30
    assert len({task.task_id for task in tasks}) == 30
    assert Counter(task.family for task in tasks) == {f"WA-{i:02d}": 3 for i in range(1, 11)}
    assert all(task.prompt.strip() and len(task.prompt) <= 8_000 for task in tasks)
    assert all(task.ground_truth.strip() for task in tasks)
    assert len(campaign_sha256(CAMPAIGN)) == 64
    assert all("C:\\Users\\" not in task.prompt for task in tasks)
    assert all("API_KEY=" not in task.prompt for task in tasks)


@pytest.mark.parametrize(
    ("total", "expected"),
    [(20, "EXCELLENT"), (18, "EXCELLENT"), (17, "USEFUL"), (14, "USEFUL"),
     (13, "PARTIAL"), (10, "PARTIAL"), (9, "WEAK"), (5, "WEAK"),
     (4, "NOT_USEFUL"), (0, "NOT_USEFUL")],
)
def test_classification_boundaries(total: int, expected: str) -> None:
    assert classify_total(total) == expected


def test_score_dimensions_are_bounded() -> None:
    score = QualificationScore("WA-01-01", 4, 4, 4, 4, 4)
    assert score_total(score) == 20
    with pytest.raises(ValueError, match="0 to 4"):
        QualificationScore("WA-01-01", 5, 4, 4, 4, 4)


def test_summary_and_broad_threshold() -> None:
    scores = [
        QualificationScore(
            f"WA-04-0{i}", 3, 3, 3, 3, 3, root_cause_correct=True, invented_facts=False
        )
        for i in range(1, 4)
    ] + [
        QualificationScore(
            f"WA-05-0{i}", 3, 3, 3, 3, 3, root_cause_correct=True, invented_facts=False
        )
        for i in range(1, 4)
    ]
    summary = summarize(scores)
    assert summary.overall_average == 15
    assert summary.coding_root_cause_correct_rate == 1.0
    assert summary.unsupported_or_invented_rate == 0.0
    assert broad_coengineer_threshold_met(summary, byte_plus_wolfram_improved=True)
    assert not broad_coengineer_threshold_met(summary, byte_plus_wolfram_improved=False)

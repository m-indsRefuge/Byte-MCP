from collections import Counter
from pathlib import Path

import pytest

from byte_mcp.wolfram.qualification import (
    QualificationScore,
    broad_coengineer_threshold_met,
    campaign_sha256,
    classify_capability_profile,
    classify_total,
    incomplete_primary_task_ids,
    load_campaign,
    score_total,
    summarize,
)

CAMPAIGN_V1 = Path("qualification/wolfram/llm-api-v1.json")
CAMPAIGN_V2 = Path("qualification/wolfram/llm-api-v2.json")


def _score(
    task_id: str,
    total_per_dimension: int = 3,
    *,
    root_cause_correct: bool | None = None,
    invented_facts: bool | None = False,
) -> QualificationScore:
    return QualificationScore(
        task_id,
        total_per_dimension,
        total_per_dimension,
        total_per_dimension,
        total_per_dimension,
        total_per_dimension,
        root_cause_correct=root_cause_correct,
        invented_facts=invented_facts,
    )


def test_v1_fixture_remains_available_for_exploratory_provenance() -> None:
    tasks = load_campaign(CAMPAIGN_V1)
    assert len(tasks) == 30
    assert len(campaign_sha256(CAMPAIGN_V1)) == 64


def test_v2_campaign_is_fixed_30_task_balanced_fixture() -> None:
    tasks = load_campaign(CAMPAIGN_V2)
    assert len(tasks) == 30
    assert len({task.task_id for task in tasks}) == 30
    assert Counter(task.family for task in tasks) == {f"WA-{i:02d}": 3 for i in range(1, 11)}
    assert all(task.prompt.strip() and len(task.prompt) <= 8_000 for task in tasks)
    assert all(task.ground_truth.strip() for task in tasks)
    assert len(campaign_sha256(CAMPAIGN_V2)) == 64
    assert all("C:\\Users\\" not in task.prompt for task in tasks)
    assert all("API_KEY=" not in task.prompt for task in tasks)


def test_v2_coding_fixture_contains_refined_defect_cases() -> None:
    tasks = {task.task_id: task for task in load_campaign(CAMPAIGN_V2)}

    assert tasks["WA-04-01"].defect_expected is False
    assert "inclusive clamping" in tasks["WA-04-01"].prompt

    assert tasks["WA-04-03"].defect_expected is True
    assert "cache.get(key)" in tasks["WA-04-03"].prompt
    assert "falsey" in tasks["WA-04-03"].ground_truth

    assert tasks["WA-05-02"].defect_expected is True
    assert "zip(a,b)" in tasks["WA-05-02"].prompt
    assert "truncates" in tasks["WA-05-02"].ground_truth

    assert tasks["WA-05-03"].defect_expected is True
    assert "pop(key,None)" in tasks["WA-05-03"].prompt
    assert "sentinel" in tasks["WA-05-03"].ground_truth


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        (20, "EXCELLENT"),
        (18, "EXCELLENT"),
        (17, "USEFUL"),
        (14, "USEFUL"),
        (13, "PARTIAL"),
        (10, "PARTIAL"),
        (9, "WEAK"),
        (5, "WEAK"),
        (4, "NOT_USEFUL"),
        (0, "NOT_USEFUL"),
    ],
)
def test_classification_boundaries(total: int, expected: str) -> None:
    assert classify_total(total) == expected


def test_score_dimensions_are_bounded() -> None:
    score = QualificationScore("WA-01-01", 4, 4, 4, 4, 4)
    assert score_total(score) == 20
    with pytest.raises(ValueError, match="0 to 4"):
        QualificationScore("WA-01-01", 5, 4, 4, 4, 4)


def test_incomplete_primary_ids_reject_duplicates_and_report_missing() -> None:
    tasks = load_campaign(CAMPAIGN_V2)
    scores = [_score(task.task_id) for task in tasks[:-1]]
    assert incomplete_primary_task_ids(tasks, scores) == ("WA-10-03",)

    duplicated = [*scores, _score("WA-01-01")]
    with pytest.raises(ValueError, match="Duplicate primary qualification score"):
        incomplete_primary_task_ids(tasks, duplicated)


def test_summary_refuses_partial_campaign() -> None:
    tasks = load_campaign(CAMPAIGN_V2)
    scores = [_score(task.task_id) for task in tasks[:-1]]
    with pytest.raises(ValueError, match="incomplete"):
        summarize(tasks, scores)


def test_coding_root_rate_uses_only_ground_truth_defect_tasks() -> None:
    tasks = load_campaign(CAMPAIGN_V2)
    scores: list[QualificationScore] = []
    for task in tasks:
        root = None
        if task.defect_expected is True:
            root = task.task_id != "WA-05-03"
        elif task.defect_expected is False:
            root = False
        scores.append(_score(task.task_id, root_cause_correct=root))

    summary = summarize(tasks, scores)
    defect_tasks = [task for task in tasks if task.defect_expected is True]
    assert len(defect_tasks) == 5
    assert summary.coding_root_cause_correct_rate == pytest.approx(4 / 5)


def test_summary_and_broad_threshold() -> None:
    tasks = load_campaign(CAMPAIGN_V2)
    scores: list[QualificationScore] = []
    for task in tasks:
        root = True if task.defect_expected is True else None
        scores.append(_score(task.task_id, root_cause_correct=root))

    summary = summarize(tasks, scores)
    assert summary.overall_average == 15
    assert summary.coding_root_cause_correct_rate == 1.0
    assert summary.unsupported_or_invented_rate == 0.0
    assert broad_coengineer_threshold_met(summary, byte_plus_wolfram_improved=True)
    assert not broad_coengineer_threshold_met(summary, byte_plus_wolfram_improved=False)


def test_capability_profiles_cover_a_b_c_and_d() -> None:
    tasks = load_campaign(CAMPAIGN_V2)

    def build_scores(
        *,
        computation_dimension: int,
        other_dimension: int,
        defect_root_correct: bool,
    ) -> list[QualificationScore]:
        computation_families = {"WA-01", "WA-02", "WA-03", "WA-07", "WA-09", "WA-10"}
        built: list[QualificationScore] = []
        for task in tasks:
            dimension = (
                computation_dimension if task.family in computation_families else other_dimension
            )
            root = defect_root_correct if task.defect_expected is True else None
            built.append(_score(task.task_id, dimension, root_cause_correct=root))
        return built

    summary_a = summarize(tasks, build_scores(
        computation_dimension=4,
        other_dimension=3,
        defect_root_correct=True,
    ))
    assert classify_capability_profile(
        summary_a, byte_plus_wolfram_improved=True
    ) == "A_BROAD_COENGINEER"

    summary_b = summarize(tasks, build_scores(
        computation_dimension=4,
        other_dimension=3,
        defect_root_correct=False,
    ))
    assert classify_capability_profile(
        summary_b, byte_plus_wolfram_improved=True
    ) == "B_COMPUTATIONAL_COENGINEER"

    summary_c = summarize(tasks, build_scores(
        computation_dimension=3,
        other_dimension=1,
        defect_root_correct=False,
    ))
    assert classify_capability_profile(
        summary_c, byte_plus_wolfram_improved=False
    ) == "C_SPECIALIST_CALCULATOR"

    summary_d = summarize(tasks, build_scores(
        computation_dimension=1,
        other_dimension=1,
        defect_root_correct=False,
    ))
    assert classify_capability_profile(
        summary_d, byte_plus_wolfram_improved=False
    ) == "D_NOT_WORTH_BROAD_INTEGRATION"
